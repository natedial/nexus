"""Build stable source spans and retrieval chunks from cleaned research text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

PAGE_MARKER_RE = re.compile(r"^--- PAGE (\d+) ---\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class SpanDraft:
    """A source-grounded span ready for durable storage."""

    span_key: str
    document_hash: str
    span_version: str
    span_type: str
    span_order: int
    text: str
    text_hash: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    coordinates: dict[str, object] | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalChunkDraft:
    """A search-oriented chunk backed by ordered source spans."""

    chunk_key: str
    document_hash: str
    chunker_version: str
    chunk_order: int
    text: str
    text_hash: str
    span_keys: tuple[str, ...]
    page_start: int | None = None
    page_end: int | None = None
    title: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class _Block:
    text: str
    char_start: int
    char_end: int
    page_start: int
    page_end: int


def build_spans_from_blocks(
    blocks: list,
    *,
    document_hash: str,
    span_version: str = "span-v3",
    key_namespace: str | None = None,
) -> list[SpanDraft]:
    """Build source spans from parser blocks, preserving page, type, and bbox."""
    from src.parser.backend import BlockType, TextBlock

    key_namespace = key_namespace or document_hash
    spans: list[SpanDraft] = []
    section_stack: list[str] = []
    paragraph_index = 0
    offset = 0

    for block in blocks:
        if not isinstance(block, TextBlock):
            continue
        text = (block.text or "").strip()
        if not text:
            continue

        if block.block_type == BlockType.HEADING:
            level = block.level if block.level and block.level > 0 else 1
            section_stack = section_stack[: level - 1]
            section_stack.append(text)
            span_type = "section"
            paragraph_start = None
            paragraph_end = None
        elif block.block_type == BlockType.TABLE:
            span_type = "table"
            paragraph_start = None
            paragraph_end = None
        elif block.block_type in {BlockType.FIGURE_REF, BlockType.CAPTION}:
            span_type = "figure"
            paragraph_start = None
            paragraph_end = None
        else:
            paragraph_index += 1
            span_type = "paragraph"
            paragraph_start = paragraph_index
            paragraph_end = paragraph_index

        page = block.page if block.page and block.page > 0 else 1
        char_start = offset
        char_end = offset + len(text)
        offset = char_end + 2
        span_order = len(spans) + 1
        text_hash = _hash_text(text)
        coordinates = {"bbox": block.bbox} if block.bbox else None
        spans.append(
            SpanDraft(
                span_key=_stable_key(
                    "span",
                    key_namespace,
                    span_version,
                    span_type,
                    str(span_order),
                    str(page),
                    str(paragraph_start or ""),
                    text_hash,
                ),
                document_hash=document_hash,
                span_version=span_version,
                span_type=span_type,
                span_order=span_order,
                text=text,
                text_hash=text_hash,
                page_start=page,
                page_end=page,
                section_path=tuple(section_stack),
                paragraph_start=paragraph_start,
                paragraph_end=paragraph_end,
                char_start=char_start,
                char_end=char_end,
                coordinates=coordinates,
            )
        )

    return spans


def build_paragraph_spans(
    text: str,
    *,
    document_hash: str,
    span_version: str = "span-v1",
    key_namespace: str | None = None,
) -> list[SpanDraft]:
    """Split cleaned document text into deterministic paragraph and section spans.

    Page markers in the form ``--- PAGE N ---`` are recognized when present.
    Without markers, all spans are assigned to page 1.
    """

    blocks = _split_blocks(text)
    key_namespace = key_namespace or document_hash
    spans: list[SpanDraft] = []
    section_stack: list[str] = []
    paragraph_index = 0

    for block in blocks:
        heading_match = HEADING_RE.match(block.text)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            section_stack = section_stack[: level - 1]
            section_stack.append(heading)
            span_type = "section"
            paragraph_start = None
            paragraph_end = None
        else:
            paragraph_index += 1
            span_type = "paragraph"
            paragraph_start = paragraph_index
            paragraph_end = paragraph_index

        span_order = len(spans) + 1
        text_hash = _hash_text(block.text)
        spans.append(
            SpanDraft(
                span_key=_stable_key(
                    "span",
                    key_namespace,
                    span_version,
                    span_type,
                    str(span_order),
                    str(block.page_start),
                    str(paragraph_start or ""),
                    text_hash,
                ),
                document_hash=document_hash,
                span_version=span_version,
                span_type=span_type,
                span_order=span_order,
                text=block.text,
                text_hash=text_hash,
                page_start=block.page_start,
                page_end=block.page_end,
                section_path=tuple(section_stack),
                paragraph_start=paragraph_start,
                paragraph_end=paragraph_end,
                char_start=block.char_start,
                char_end=block.char_end,
            )
        )

    return spans


def build_figure_spans(
    figures: list[dict],
    *,
    document_hash: str,
    span_version: str = "span-v3",
    key_namespace: str | None = None,
    start_order: int = 1,
) -> list[SpanDraft]:
    """One citeable span per chart that has a content-addressed figure_key."""
    key_namespace = key_namespace or document_hash
    spans: list[SpanDraft] = []
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        figure_key = figure.get("figure_key")
        if not isinstance(figure_key, str) or not figure_key.strip():
            continue
        figure_key = figure_key.strip()
        caption = figure.get("caption_text")
        label = figure.get("figure_id") or figure_key
        text = caption.strip() if isinstance(caption, str) and caption.strip() else str(label)
        page = figure.get("page")
        page_number = int(page) if isinstance(page, int) and page > 0 else None
        bbox = figure.get("bbox")
        coordinates = {"bbox": bbox} if isinstance(bbox, list) else None
        text_hash = _hash_text(text)
        span_order = start_order + len(spans)
        spans.append(
            SpanDraft(
                span_key=_stable_key(
                    "span",
                    key_namespace,
                    span_version,
                    "figure",
                    figure_key,
                    str(page_number or ""),
                    text_hash,
                ),
                document_hash=document_hash,
                span_version=span_version,
                span_type="figure",
                span_order=span_order,
                text=text,
                text_hash=text_hash,
                page_start=page_number,
                page_end=page_number,
                coordinates=coordinates,
                metadata={
                    "figure_key": figure_key,
                    "figure_id": str(label),
                    "caption_text": text,
                    "content_hash": figure.get("content_hash") or "",
                    "page": page_number,
                    "bbox": bbox if isinstance(bbox, list) else None,
                },
            )
        )
    return spans


def build_retrieval_chunks(
    spans: list[SpanDraft],
    *,
    document_hash: str,
    chunker_version: str = "retrieval-chunker-v1",
    key_namespace: str | None = None,
    target_chars: int = 6000,
    min_chars: int = 1800,
    overlap_spans: int = 1,
) -> list[RetrievalChunkDraft]:
    """Pack spans into deterministic retrieval chunks."""

    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    if min_chars <= 0:
        raise ValueError("min_chars must be positive")
    if overlap_spans < 0:
        raise ValueError("overlap_spans must be non-negative")

    key_namespace = key_namespace or document_hash
    chunks: list[list[SpanDraft]] = []
    current: list[SpanDraft] = []
    current_len = 0

    for span in spans:
        span_len = len(span.text)
        projected = current_len + span_len + (2 if current else 0)
        if current and projected > target_chars and current_len >= min_chars:
            chunks.append(current)
            current = current[-overlap_spans:] if overlap_spans else []
            current_len = sum(len(item.text) for item in current)
            projected = current_len + span_len + (2 if current else 0)

        current.append(span)
        current_len = projected

    if current:
        chunks.append(current)

    drafts: list[RetrievalChunkDraft] = []
    for index, chunk_spans in enumerate(chunks, start=1):
        chunk_text = "\n\n".join(span.text for span in chunk_spans)
        text_hash = _hash_text(chunk_text)
        page_values = [
            page
            for span in chunk_spans
            for page in (span.page_start, span.page_end)
            if page is not None
        ]
        title = _chunk_title(chunk_spans)
        drafts.append(
            RetrievalChunkDraft(
                chunk_key=_stable_key(
                    "chunk",
                    key_namespace,
                    chunker_version,
                    str(index),
                    text_hash,
                ),
                document_hash=document_hash,
                chunker_version=chunker_version,
                chunk_order=index,
                text=chunk_text,
                text_hash=text_hash,
                span_keys=tuple(span.span_key for span in chunk_spans),
                page_start=min(page_values) if page_values else None,
                page_end=max(page_values) if page_values else None,
                title=title,
                metadata={
                    "span_count": len(chunk_spans),
                    "section_path": list(chunk_spans[-1].section_path),
                },
            )
        )

    return drafts


def _split_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    current_lines: list[str] = []
    current_start: int | None = None
    current_page_start = 1
    current_page = 1
    offset = 0

    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(raw_line)
        stripped = raw_line.strip()
        page_match = PAGE_MARKER_RE.match(stripped)

        if page_match:
            _flush_block(
                blocks,
                current_lines,
                current_start,
                line_start,
                current_page_start,
                current_page,
            )
            current_lines = []
            current_start = None
            current_page = int(page_match.group(1))
            current_page_start = current_page
            offset = line_end
            continue

        if not stripped:
            _flush_block(
                blocks,
                current_lines,
                current_start,
                line_start,
                current_page_start,
                current_page,
            )
            current_lines = []
            current_start = None
            current_page_start = current_page
            offset = line_end
            continue

        if current_start is None:
            current_start = line_start
            current_page_start = current_page
        current_lines.append(raw_line)
        offset = line_end

    _flush_block(
        blocks,
        current_lines,
        current_start,
        len(text),
        current_page_start,
        current_page,
    )
    return blocks


def _flush_block(
    blocks: list[_Block],
    lines: list[str],
    start: int | None,
    end: int,
    page_start: int,
    page_end: int,
) -> None:
    if start is None or not lines:
        return
    block_text = "".join(lines).strip()
    if not block_text:
        return
    blocks.append(
        _Block(
            text=block_text,
            char_start=start,
            char_end=end,
            page_start=page_start,
            page_end=page_end,
        )
    )


def _chunk_title(spans: list[SpanDraft]) -> str | None:
    for span in spans:
        if span.span_type == "section":
            return span.text.lstrip("# ").strip()
    for span in spans:
        if span.section_path:
            return span.section_path[-1]
    return None


def _stable_key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
