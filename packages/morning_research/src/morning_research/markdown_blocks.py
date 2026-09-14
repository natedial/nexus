"""Convert markdown text into Notion block objects.

Adapted from `family_ceo_review.family_ceo_review.notion_publish`. Supports
headings, paragraphs, bullet/numbered lists, simple pipe tables, and
dividers, with plain (non-rich) text split to Notion's 2000-character rich
text limit.
"""

from __future__ import annotations

import re
from typing import Any

NOTION_TEXT_LIMIT = 2000
BLOCK_BATCH_LIMIT = 100


def _rich_text_chunks(text: str) -> list[dict[str, Any]]:
    """Split `text` into <=2000-char plain rich-text objects."""
    if not text:
        return [{"type": "text", "text": {"content": ""}}]
    chunks = [text[i : i + NOTION_TEXT_LIMIT] for i in range(0, len(text), NOTION_TEXT_LIMIT)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks]


def paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text_chunks(text)},
    }


def heading_block(level: int, text: str) -> dict[str, Any]:
    clean = text.strip()
    if level <= 1:
        block_type = "heading_1"
    elif level == 2:
        block_type = "heading_2"
    else:
        block_type = "heading_3"
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text_chunks(clean)},
    }


def bulleted_list_item_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text_chunks(text)},
    }


def numbered_list_item_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": _rich_text_chunks(text)},
    }


def divider_block() -> dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def table_row_block(cells: list[str]) -> dict[str, Any]:
    return {
        "type": "table_row",
        "table_row": {"cells": [_rich_text_chunks(cell.strip()) for cell in cells]},
    }


def table_block(rows: list[list[str]]) -> dict[str, Any]:
    if not rows:
        return paragraph_block("")
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            "children": [table_row_block(row) for row in normalized],
        },
    }


def _is_table_separator(row: str) -> bool:
    stripped = row.replace("|", "").strip()
    return bool(stripped) and set(stripped) <= {"-", ":", " "}


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Convert a markdown document into a flat list of Notion block objects."""
    lines = markdown.splitlines()
    blocks: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped == "---":
            blocks.append(divider_block())
            index += 1
            continue

        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            blocks.append(heading_block(level, text))
            index += 1
            continue

        if stripped.startswith("|") and "|" in stripped[1:]:
            table_rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = lines[index].strip()
                if _is_table_separator(row):
                    index += 1
                    continue
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                table_rows.append(cells)
                index += 1
            if table_rows:
                blocks.append(table_block(table_rows))
            continue

        if re.match(r"^[-*] ", stripped):
            blocks.append(bulleted_list_item_block(stripped[2:].strip()))
            index += 1
            continue

        numbered_match = re.match(r"^\d+\.\s+(.+)$", stripped)
        if numbered_match:
            blocks.append(numbered_list_item_block(numbered_match.group(1)))
            index += 1
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            nxt = lines[index].strip()
            if (
                not nxt
                or nxt.startswith("#")
                or nxt == "---"
                or nxt.startswith("|")
                or re.match(r"^[-*] ", nxt)
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            paragraph_lines.append(nxt)
            index += 1
        blocks.append(paragraph_block(" ".join(paragraph_lines)))

    return blocks


def chunk_blocks(blocks: list[dict[str, Any]], batch_size: int = BLOCK_BATCH_LIMIT) -> list[list[dict[str, Any]]]:
    """Split a flat block list into batches respecting Notion's 100-block limit."""
    return [blocks[i : i + batch_size] for i in range(0, len(blocks), batch_size)]


def extract_title(markdown: str, *, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback
