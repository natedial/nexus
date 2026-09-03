"""Artifact writing utilities for parsed documents."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .backend import BlockType, FigureRecord, TextBlock, TextParseResult

_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_BULLET_RE = re.compile(r"^[-*+]\s+\S")
_NUMBERED_RE = re.compile(r"^\d+\.\s+\S")


def _is_list_line(stripped: str) -> bool:
    return bool(
        _BULLET_RE.match(stripped)
        or _NUMBERED_RE.match(stripped)
        or stripped.startswith("• ")
    )


def normalize_markdown(markdown: str) -> str:
    """Normalize parser markdown to keep paragraph boundaries stable."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    normalized: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        needs_blank_before = False
        if stripped and normalized:
            prev = normalized[-1].strip()
            if prev:
                is_heading = bool(_HEADING_RE.match(stripped))
                is_list = _is_list_line(stripped)
                prev_is_list = _is_list_line(prev)
                if is_heading or (is_list and not prev_is_list):
                    needs_blank_before = True

        if needs_blank_before:
            normalized.append("")
        normalized.append(line)

    result = "\n".join(normalized)
    return re.sub(r"\n{3,}", "\n\n", result)


def paragraph_stats(markdown: str) -> tuple[int, int, int]:
    text = normalize_markdown(markdown).strip()
    if not text:
        return 0, 0, 0

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    total_chars = len(text)
    max_paragraph_chars = max((len(p) for p in paragraphs), default=0)
    return len(paragraphs), max_paragraph_chars, total_chars


def block_to_dict(block: TextBlock) -> dict:
    return {
        "block_type": block.block_type.value,
        "text": block.text,
        "page": block.page,
        "level": block.level,
        "bbox": block.bbox,
    }


def block_from_dict(payload: dict) -> TextBlock:
    return TextBlock(
        block_type=BlockType(payload["block_type"]),
        text=str(payload.get("text") or ""),
        page=payload.get("page"),
        level=payload.get("level"),
        bbox=payload.get("bbox"),
    )


def blocks_to_markdown(
    blocks: list[TextBlock],
    *,
    include_page_markers: bool = False,
) -> str:
    parts: list[str] = []
    current_page: int | None = None
    for block in blocks:
        if not block.text or not block.text.strip():
            continue

        if include_page_markers:
            page = block.page if block.page and block.page > 0 else None
            if page is not None and page != current_page:
                parts.append(f"--- PAGE {page} ---")
                current_page = page

        if block.block_type == BlockType.HEADING:
            level = block.level if block.level and block.level > 0 else 1
            prefix = "#" * min(level, 6)
            parts.append(f"{prefix} {block.text.strip()}")
        elif block.block_type == BlockType.LIST_ITEM:
            parts.append(f"- {block.text.strip()}")
        elif block.block_type == BlockType.FIGURE_REF:
            caption = block.text.strip()
            parts.append(f"[Figure] {caption}" if caption else "[Figure]")
        else:
            parts.append(block.text.strip())

    return "\n\n".join(parts)


def filter_blocks_present_in_text(
    blocks: list[TextBlock],
    text: str,
) -> list[TextBlock]:
    """Keep blocks whose text still appears after boilerplate cleanup."""
    if not text or not blocks:
        return list(blocks)
    kept = [
        block
        for block in blocks
        if block.text and block.text.strip() and block.text.strip() in text
    ]
    return kept or list(blocks)


def load_blocks(path: Path) -> list[TextBlock]:
    if not path.exists():
        return []
    blocks: list[TextBlock] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        blocks.append(block_from_dict(json.loads(stripped)))
    return blocks


def markdown_to_blocks(markdown: str) -> list[TextBlock]:
    markdown = normalize_markdown(markdown)
    blocks: list[TextBlock] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines.clear()
        if text:
            blocks.append(TextBlock(block_type=BlockType.PARAGRAPH, text=text))

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            continue

        if stripped.startswith("#"):
            flush_paragraph()
            level = len(stripped) - len(stripped.lstrip("#"))
            content = stripped[level:].strip()
            if content:
                blocks.append(
                    TextBlock(
                        block_type=BlockType.HEADING,
                        text=content,
                        level=max(1, min(level, 6)),
                    )
                )
            continue

        if re.match(r"^[-*+]\s+", stripped):
            flush_paragraph()
            content = re.sub(r"^[-*+]\s+", "", stripped, count=1).strip()
            if content:
                blocks.append(TextBlock(block_type=BlockType.LIST_ITEM, text=content))
            continue

        if re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            content = re.sub(r"^\d+\.\s+", "", stripped, count=1).strip()
            if content:
                blocks.append(TextBlock(block_type=BlockType.LIST_ITEM, text=content))
            continue

        if stripped.startswith("• "):
            flush_paragraph()
            content = stripped[2:].strip()
            if content:
                blocks.append(TextBlock(block_type=BlockType.LIST_ITEM, text=content))
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()
    return blocks


def _normalize_bbox(bbox) -> list[float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, list):
        return bbox
    if isinstance(bbox, tuple):
        return list(bbox)
    for attr in ("tolist", "to_list", "to_tuple", "as_tuple"):
        fn = getattr(bbox, attr, None)
        if callable(fn):
            try:
                value = fn()
                if isinstance(value, tuple):
                    return list(value)
                if isinstance(value, list):
                    return value
            except Exception:
                break
    return None


def _resolve_value(value):
    if callable(value):
        try:
            value = value()
        except Exception:
            return None
    return value


def _figure_to_dict(record: FigureRecord) -> dict:
    caption = _resolve_value(record.caption_text)
    image_path = _resolve_value(record.image_path)
    content_hash = _resolve_value(record.content_hash)
    section_path = record.section_path if record.section_path else []

    if callable(section_path):
        section_path = _resolve_value(section_path) or []

    if section_path is None:
        section_path = []

    return {
        "figure_id": record.figure_id,
        "page": record.page,
        "section_path": list(section_path) if isinstance(section_path, (list, tuple)) else [],
        "bbox": _normalize_bbox(_resolve_value(record.bbox)),
        "caption_text": caption if isinstance(caption, str) or caption is None else str(caption),
        "image_path": (
            image_path if isinstance(image_path, str) or image_path is None else str(image_path)
        ),
        "content_hash": (
            content_hash
            if isinstance(content_hash, str) or content_hash is None
            else str(content_hash)
        ),
    }


def write_artifacts(
    artifact_dir: Path, text_result: TextParseResult, figures: list[FigureRecord]
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)

    figures_dir = artifact_dir / "figures"
    if any(record.image_path for record in figures):
        figures_dir.mkdir(parents=True, exist_ok=True)
        for record in figures:
            if not record.image_path:
                continue
            src = Path(record.image_path)
            if not src.exists():
                continue
            ext = src.suffix or ".png"
            filename = f"{record.figure_id}{ext}"
            dest = figures_dir / filename
            if dest.resolve() != src.resolve():
                shutil.copyfile(src, dest)
            record.image_path = str(Path("figures") / filename)

    content = (
        text_result.raw_output
        if text_result.raw_output is not None
        else blocks_to_markdown(text_result.blocks)
    )
    if any(record.image_path for record in figures):
        content += "\n\n## Figures\n"
        for idx, record in enumerate(figures, start=1):
            if not record.image_path:
                continue
            label = f"Figure {idx}"
            if record.caption_text:
                alt_text = f"{label}: {record.caption_text}"
            else:
                alt_text = label
            content += f"\n\n![{alt_text}]({record.image_path})"
    if not content.endswith("\n"):
        content = f"{content}\n"

    document_path = artifact_dir / "document.md"
    document_path.write_text(content, encoding="utf-8")

    blocks_path = artifact_dir / "blocks.jsonl"
    if text_result.blocks:
        block_lines = [json.dumps(block_to_dict(block)) for block in text_result.blocks]
        blocks_path.write_text("\n".join(block_lines) + "\n", encoding="utf-8")
    else:
        blocks_path.write_text("", encoding="utf-8")

    figures_path = artifact_dir / "figures.jsonl"
    if figures:
        lines = [json.dumps(_figure_to_dict(record)) for record in figures]
        figures_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        figures_path.write_text("", encoding="utf-8")
