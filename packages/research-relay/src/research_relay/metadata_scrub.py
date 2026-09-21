from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from io import BytesIO

_PLAIN_TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".xml"}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}
_OOXML_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
_LEGACY_OFFICE_EXTENSIONS = {".doc", ".xls", ".ppt", ".odt", ".ods", ".odp"}
_OOXML_METADATA_PARTS = {
    "docProps/core.xml",
    "docProps/app.xml",
    "docProps/custom.xml",
}


@dataclass(frozen=True)
class MetadataScrubResult:
    ok: bool
    payload: bytes
    reason: str = ""
    scrubbed: bool = False


def _extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def scrub_attachment_metadata(
    payload: bytes,
    filename: str,
    content_type: str = "",
) -> MetadataScrubResult:
    """Strip embedded file metadata. Fail closed when scrubbing is required."""
    data = payload or b""
    ext = _extension(filename)
    ctype = (content_type or "").lower()

    if ext in _PLAIN_TEXT_EXTENSIONS:
        return MetadataScrubResult(ok=True, payload=data, scrubbed=False)

    if ext == ".pdf" or data.startswith(b"%PDF"):
        return _scrub_pdf(data)

    if ext in _IMAGE_EXTENSIONS or ctype.startswith("image/"):
        return _scrub_image(data, ext=ext, content_type=ctype)

    if ext in _OOXML_EXTENSIONS:
        return _scrub_ooxml(data, ext)

    if ext in _LEGACY_OFFICE_EXTENSIONS:
        return MetadataScrubResult(
            ok=False,
            payload=data,
            reason=f"metadata scrub not supported for legacy office type {ext or '[none]'}",
        )

    if _looks_binary(data):
        return MetadataScrubResult(
            ok=False,
            payload=data,
            reason=(
                f"metadata scrub not supported for binary attachment type {ext or ctype or '[unknown]'}"
            ),
        )

    return MetadataScrubResult(ok=True, payload=data, scrubbed=False)


def _looks_binary(payload: bytes) -> bool:
    if not payload:
        return False
    sample = payload[:8192]
    if b"\x00" in sample:
        return True
    # High ratio of non-text bytes suggests a structured binary format.
    non_text = sum(1 for byte in sample if byte < 9 or (13 < byte < 32) or byte > 126)
    return non_text / max(len(sample), 1) > 0.30


def _scrub_pdf(payload: bytes) -> MetadataScrubResult:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"pdf metadata scrub unavailable: {exc}",
        )

    try:
        reader = PdfReader(BytesIO(payload))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        # pypdf 5.x: clear inherited metadata rather than copying source properties.
        if getattr(writer, "metadata", None) is not None:
            writer.metadata = {}
        out = BytesIO()
        writer.write(out)
        cleaned = out.getvalue()
    except Exception as exc:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"pdf metadata scrub failed: {exc}",
        )

    if not cleaned.startswith(b"%PDF"):
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason="pdf metadata scrub produced invalid output",
        )
    return MetadataScrubResult(ok=True, payload=cleaned, scrubbed=True)


def _scrub_image(payload: bytes, *, ext: str, content_type: str) -> MetadataScrubResult:
    try:
        from PIL import Image
    except ImportError as exc:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"image metadata scrub unavailable: {exc}",
        )

    format_hint = _image_format(ext, content_type)
    if format_hint is None:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"image metadata scrub not supported for type {ext or content_type}",
        )

    try:
        with Image.open(BytesIO(payload)) as image:
            cleaned = Image.new(image.mode, image.size)
            cleaned.putdata(list(image.getdata()))
            if image.mode in {"P", "PA"} and image.palette is not None:
                cleaned.putpalette(image.palette)
            out = BytesIO()
            save_kwargs: dict[str, object] = {}
            if format_hint == "JPEG":
                save_kwargs["quality"] = 95
            cleaned.save(out, format=format_hint, **save_kwargs)
            data = out.getvalue()
    except Exception as exc:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"image metadata scrub failed: {exc}",
        )

    return MetadataScrubResult(ok=True, payload=data, scrubbed=True)


def _image_format(ext: str, content_type: str) -> str | None:
    if ext in {".jpg", ".jpeg"} or content_type in {"image/jpeg", "image/jpg"}:
        return "JPEG"
    if ext == ".png" or content_type == "image/png":
        return "PNG"
    if ext == ".gif" or content_type == "image/gif":
        return "GIF"
    if ext == ".webp" or content_type == "image/webp":
        return "WEBP"
    if ext in {".tif", ".tiff"} or content_type in {"image/tiff", "image/tif"}:
        return "TIFF"
    return None


def _scrub_ooxml(payload: bytes, ext: str) -> MetadataScrubResult:
    try:
        with zipfile.ZipFile(BytesIO(payload), "r") as source:
            out = BytesIO()
            with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as dest:
                for info in source.infolist():
                    if info.filename in _OOXML_METADATA_PARTS:
                        continue
                    dest.writestr(info, source.read(info.filename))
            cleaned = out.getvalue()
    except Exception as exc:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"ooxml metadata scrub failed: {exc}",
        )

    if not cleaned:
        return MetadataScrubResult(
            ok=False,
            payload=payload,
            reason=f"ooxml metadata scrub produced empty output for {ext}",
        )
    return MetadataScrubResult(ok=True, payload=cleaned, scrubbed=True)
