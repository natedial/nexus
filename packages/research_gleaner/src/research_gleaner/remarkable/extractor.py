from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from research_gleaner.models import (
    CapturedExcerpt,
    CaptureIntent,
    SourceDocumentRef,
    SourceLocator,
    normalize_text,
)
from research_gleaner.remarkable.client import RemarkableDocument

REMARKABLE_EXTRACTOR_VERSION = 3

REMARKABLE_HIGHLIGHT_RGBA = {
    (255, 237, 117, 255): "yellow",
    (190, 234, 254, 255): "blue",
    (242, 158, 255, 255): "pink",
    (255, 195, 140, 255): "orange",
    (172, 255, 133, 255): "green",
}


@dataclass(frozen=True, slots=True)
class HighlightFragment:
    page_number: int
    page_id: str
    text: str
    color_id: int
    color_name: str
    color_rgba: tuple[int, int, int, int] | None
    rectangles: tuple[tuple[float, float, float, float], ...]

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        if not self.rectangles:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(rectangle[0] for rectangle in self.rectangles),
            min(rectangle[1] for rectangle in self.rectangles),
            max(rectangle[0] + rectangle[2] for rectangle in self.rectangles),
            max(rectangle[1] + rectangle[3] for rectangle in self.rectangles),
        )


def extract_document(
    document: RemarkableDocument,
    archive: bytes,
    *,
    routes: dict[str, CaptureIntent] | None = None,
) -> list[CapturedExcerpt]:
    fragments = extract_fragments(archive)
    source = SourceDocumentRef(
        source_kind="remarkable",
        document_id=document.document_id,
        uri=f"remarkable:///{quote(document.path.lstrip('/'))}",
        title=document.title,
        modified_at=document.modified_at,
        metadata={
            "path": document.path,
            "file_type": "pdf",
            "revision": document.revision,
        },
    )
    captures = []
    for group in merge_fragments(fragments):
        text = normalize_text(" ".join(fragment.text for fragment in group))
        style = _source_style(group[0])
        bounds = _group_bounds(group)
        annotation_id = _annotation_id(document.document_id, group)
        locator = SourceLocator(
            page_number=group[0].page_number,
            annotation_id=annotation_id,
            coordinates=bounds,
            metadata={"page_id": group[0].page_id},
        )
        captures.append(
            CapturedExcerpt.create(
                document=source,
                locator=locator,
                text=text,
                context_text=text,
                source_style=style,
                intent=(routes or {}).get(style, CaptureIntent.HOLD),
                metadata={
                    "remarkable_color_id": group[0].color_id,
                    "remarkable_color_enum": group[0].color_name,
                    "remarkable_color_rgba": (
                        list(group[0].color_rgba) if group[0].color_rgba else None
                    ),
                    "remarkable_fragments": [
                        {
                            "text": fragment.text,
                            "rectangles": [list(rectangle) for rectangle in fragment.rectangles],
                        }
                        for fragment in group
                    ],
                },
            )
        )
    return captures


def extract_fragments(archive: bytes) -> list[HighlightFragment]:
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        page_order = _page_order(source)
        page_numbers = {page_id: index + 1 for index, page_id in enumerate(page_order)}
        fragments = []
        for name in source.namelist():
            if not name.endswith(".rm"):
                continue
            page_id = name.rsplit("/", 1)[-1].removesuffix(".rm")
            page_number = page_numbers.get(page_id)
            if page_number is None:
                continue
            fragments.extend(_read_rm_fragments(source.read(name), page_number, page_id))
    return sorted(
        fragments,
        key=lambda fragment: (
            fragment.page_number,
            fragment.bounds[1],
            fragment.bounds[0],
        ),
    )


def merge_fragments(
    fragments: list[HighlightFragment],
) -> list[list[HighlightFragment]]:
    groups: list[list[HighlightFragment]] = []
    for fragment in fragments:
        if groups and _adjacent(groups[-1][-1], fragment):
            groups[-1].append(fragment)
        else:
            groups.append([fragment])
    return groups


def _read_rm_fragments(
    data: bytes,
    page_number: int,
    page_id: str,
) -> list[HighlightFragment]:
    import rmscene

    tree = rmscene.read_tree(io.BytesIO(data))
    fragments = []
    for item in tree.walk():
        if type(item).__name__ != "GlyphRange":
            continue
        text = normalize_text(str(getattr(item, "text", "") or ""))
        if not text:
            continue
        color = getattr(item, "color", None)
        color_id = int(getattr(color, "value", color if color is not None else 9))
        color_name = str(getattr(color, "name", "highlight") or "highlight").lower()
        raw_rgba = getattr(item, "color_rgba", None)
        color_rgba = tuple(int(channel) for channel in raw_rgba) if raw_rgba else None
        rectangles = tuple(
            (float(rectangle.x), float(rectangle.y), float(rectangle.w), float(rectangle.h))
            for rectangle in (getattr(item, "rectangles", None) or ())
        )
        fragments.append(
            HighlightFragment(
                page_number=page_number,
                page_id=page_id,
                text=text,
                color_id=color_id,
                color_name=color_name,
                color_rgba=color_rgba,
                rectangles=rectangles,
            )
        )
    return fragments


def _page_order(source: zipfile.ZipFile) -> list[str]:
    for name in source.namelist():
        if not name.endswith(".content"):
            continue
        payload = json.loads(source.read(name))
        pages = payload.get("cPages", {}).get("pages", [])
        page_order = [str(page["id"]) for page in pages if page.get("id")]
        if page_order:
            return page_order
        legacy_pages = payload.get("pages", [])
        page_order = [
            str(page.get("id") if isinstance(page, dict) else page)
            for page in legacy_pages
            if (page.get("id") if isinstance(page, dict) else page)
        ]
        if page_order:
            return page_order
    return []


def _adjacent(previous: HighlightFragment, current: HighlightFragment) -> bool:
    if (
        previous.page_number != current.page_number
        or previous.color_id != current.color_id
        or not previous.rectangles
        or not current.rectangles
    ):
        return False
    px0, py0, px1, py1 = previous.bounds
    cx0, cy0, _cx1, cy1 = current.bounds
    line_height = max(py1 - py0, cy1 - cy0, 1.0)
    same_line = abs(((py0 + py1) / 2) - ((cy0 + cy1) / 2)) <= line_height * 0.5
    if same_line:
        return cx0 - px1 <= line_height * 2
    return 0 <= cy0 - py1 <= line_height * 1.5 and cx0 <= px1 + line_height * 4


def _group_bounds(group: list[HighlightFragment]) -> tuple[float, float, float, float]:
    bounds = [fragment.bounds for fragment in group]
    return (
        min(value[0] for value in bounds),
        min(value[1] for value in bounds),
        max(value[2] for value in bounds),
        max(value[3] for value in bounds),
    )


def _source_style(fragment: HighlightFragment) -> str:
    rgba = fragment.color_rgba
    if rgba and rgba != (0, 0, 0, 255):
        return REMARKABLE_HIGHLIGHT_RGBA.get(
            rgba,
            "rgba-" + "-".join(str(channel) for channel in rgba),
        )
    return fragment.color_name.lower()


def _annotation_id(document_id: str, group: list[HighlightFragment]) -> str:
    payload: dict[str, Any] = {
        "document_id": document_id,
        "page_number": group[0].page_number,
        "color_id": group[0].color_id,
        "color_rgba": group[0].color_rgba,
        "fragments": [
            {"text": fragment.text, "rectangles": fragment.rectangles} for fragment in group
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "rma_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
