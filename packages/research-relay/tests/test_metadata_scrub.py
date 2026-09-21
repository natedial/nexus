from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from research_relay.attachments import AttachmentDecision, AttachmentPolicy
from research_relay.metadata_scrub import scrub_attachment_metadata
from research_relay.reconstruct import ReconstructionSettings, reconstruct_message


def _pdf_with_metadata() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata(
        {
            "/Title": "Secret title",
            "/Author": "Alice Private",
            "/Subject": "internal",
            "/Creator": "Word",
        }
    )
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _jpeg_with_exif() -> bytes:
    image = Image.new("RGB", (8, 8), color=(10, 20, 30))
    exif = image.getexif()
    exif[0x010E] = "Artist: private.user@gmail.com"
    exif[0x0131] = "Software: test"
    out = BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _docx_with_props() -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
            "<dc:creator>Alice</dc:creator></cp:coreProperties>",
        )
        archive.writestr("word/document.xml", "<w:document/>")
    return out.getvalue()


def test_scrub_pdf_removes_document_metadata() -> None:
    payload = _pdf_with_metadata()
    result = scrub_attachment_metadata(payload, "report.pdf", "application/pdf")
    assert result.ok is True
    assert result.scrubbed is True
    cleaned = PdfReader(BytesIO(result.payload))
    meta = cleaned.metadata or {}
    assert not any(meta.get(key) for key in ("/Author", "/Title", "/Subject", "/Creator"))


def test_scrub_jpeg_removes_exif() -> None:
    payload = _jpeg_with_exif()
    result = scrub_attachment_metadata(payload, "scan.jpg", "image/jpeg")
    assert result.ok is True
    assert result.scrubbed is True
    cleaned = Image.open(BytesIO(result.payload))
    assert not cleaned.getexif()


def test_scrub_docx_drops_docprops() -> None:
    payload = _docx_with_props()
    result = scrub_attachment_metadata(
        payload,
        "memo.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert result.ok is True
    assert result.scrubbed is True
    with zipfile.ZipFile(BytesIO(result.payload), "r") as archive:
        assert "docProps/core.xml" not in archive.namelist()
        assert "word/document.xml" in archive.namelist()


def test_legacy_doc_fails_closed() -> None:
    result = scrub_attachment_metadata(b"legacy", "memo.doc", "application/msword")
    assert result.ok is False
    assert "legacy office" in result.reason


def test_plain_text_passes_through() -> None:
    payload = b"hello world"
    result = scrub_attachment_metadata(payload, "notes.txt", "text/plain")
    assert result.ok is True
    assert result.payload == payload
    assert result.scrubbed is False


def test_reconstruct_skips_pdf_when_scrub_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from email import policy
    from email.message import EmailMessage
    from email.parser import BytesParser
    from pathlib import Path

    from research_relay.metadata_scrub import MetadataScrubResult

    fixture = Path(__file__).parent / "fixtures" / "multiple_attachments.eml"
    original = BytesParser(policy=policy.default).parsebytes(fixture.read_bytes())

    def _fail_pdf(payload: bytes, filename: str, content_type: str = "") -> MetadataScrubResult:
        if filename.endswith(".pdf") or payload.startswith(b"%PDF"):
            return MetadataScrubResult(ok=False, payload=payload, reason="pdf scrub failed")
        return scrub_attachment_metadata(payload, filename, content_type)

    monkeypatch.setattr("research_relay.reconstruct.scrub_attachment_metadata", _fail_pdf)

    settings = ReconstructionSettings(
        proton_from="relay@proton.me",
        reply_to="relay-reply@proton.me",
        private_address="private.user@gmail.com",
        hmac_key=b"unit-test-hmac-key",
        message_id_domain="relay.local",
        attachment_policy=AttachmentPolicy(
            max_individual_bytes=50_000,
            max_combined_bytes=100_000,
            blocked_extensions=(".exe",),
            allowed_extensions=(),
            on_prohibited="skip",
            private_address="private.user@gmail.com",
        ),
    )
    rebuilt = reconstruct_message(original, gmail_msgid="999", settings=settings)
    pdf_results = [item for item in rebuilt.attachments if item.safe_filename.endswith(".pdf")]
    assert pdf_results
    assert all(item.action == AttachmentDecision.SKIP for item in pdf_results)
    assert any("pdf scrub failed" in note for note in rebuilt.notes)

    outgoing = rebuilt.message
    attachment_names = [
        part.get_filename()
        for part in outgoing.walk()
        if part.get_content_disposition() == "attachment"
    ]
    assert not any(name and name.endswith(".pdf") for name in attachment_names)
