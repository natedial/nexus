from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from research_gleaner.models import (
    CapturedExcerpt,
    CaptureIntent,
    SourceDocumentRef,
    SourceLocator,
)
from research_gleaner.notion.query import page_multi_select, page_title

HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
RICH_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
}


@dataclass(frozen=True, slots=True)
class ColorRule:
    intent: CaptureIntent = CaptureIntent.HOLD


DEFAULT_COLOR_RULES: dict[str, ColorRule] = {
    color: ColorRule()
    for color in (
        "green",
        "orange",
        "purple",
        "pink",
        "pink_background",
        "yellow",
        "blue",
    )
}


class NotionExtractor:
    def __init__(
        self,
        client: Any,
        *,
        color_rules: dict[str, ColorRule] | None = None,
        title_property: str = "Name",
        topics_property: str = "Topics",
        resource_type_property: str = "Resource Type",
    ):
        self.client = client
        self.color_rules = dict(color_rules or DEFAULT_COLOR_RULES)
        self.title_property = title_property
        self.topics_property = topics_property
        self.resource_type_property = resource_type_property

    def extract_page(self, page: dict[str, Any]) -> list[CapturedExcerpt]:
        page_id = str(page["id"])
        page_url = str(page.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}")
        modified_at = _parse_datetime(page.get("last_edited_time"))
        document = SourceDocumentRef(
            source_kind="notion",
            document_id=page_id,
            uri=page_url,
            title=page_title(page, self.title_property),
            modified_at=modified_at,
            metadata={
                "topics": list(page_multi_select(page, self.topics_property)),
                "resource_types": list(page_multi_select(page, self.resource_type_property)),
            },
        )
        walker = _BlockWalker(self.client, document, self.color_rules)
        walker.walk(page_id)
        return _dedupe(walker.captures)


class _BlockWalker:
    def __init__(
        self,
        client: Any,
        document: SourceDocumentRef,
        color_rules: dict[str, ColorRule],
    ):
        self.client = client
        self.document = document
        self.color_rules = color_rules
        self.heading_trail: list[tuple[int, str]] = []
        self.captures: list[CapturedExcerpt] = []
        self.visited_containers: set[str] = set()

    def walk(self, block_id: str) -> None:
        if block_id in self.visited_containers:
            return
        self.visited_containers.add(block_id)
        blocks = self.client.paginate(
            lambda start_cursor=None: self.client.list_block_children(
                block_id,
                start_cursor=start_cursor,
            )
        )
        for block in blocks:
            self._visit(block)

    def _visit(self, block: dict[str, Any]) -> None:
        block_type = str(block.get("type", ""))
        if block_type == "table":
            self._walk_table(block)
            return
        if block_type in HEADING_TYPES:
            level = _heading_level(block_type)
            text = _block_plain_text(block).strip()
            if text:
                self.heading_trail = [item for item in self.heading_trail if item[0] < level]
                self.heading_trail.append((level, text))
        if block_type in RICH_TEXT_BLOCK_TYPES:
            self._extract_rich_text(
                block_id=str(block["id"]),
                block_type=block_type,
                rich_text=_block_rich_text(block),
                locator_metadata={},
            )
        if block.get("has_children"):
            self.walk(str(block["id"]))
        if block_type == "synced_block":
            synced_from = block.get("synced_block", {}).get("synced_from") or {}
            source_id = synced_from.get("block_id")
            if source_id:
                self.walk(str(source_id))

    def _walk_table(self, table: dict[str, Any]) -> None:
        rows = self.client.paginate(
            lambda start_cursor=None: self.client.list_block_children(
                str(table["id"]),
                start_cursor=start_cursor,
            )
        )
        for row in rows:
            if row.get("type") != "table_row":
                continue
            for cell_index, cell in enumerate(row.get("table_row", {}).get("cells", [])):
                self._extract_rich_text(
                    block_id=str(row["id"]),
                    block_type="table_cell",
                    rich_text=cell,
                    locator_metadata={
                        "table_id": str(table["id"]),
                        "cell_index": cell_index,
                    },
                )

    def _extract_rich_text(
        self,
        *,
        block_id: str,
        block_type: str,
        rich_text: list[dict[str, Any]],
        locator_metadata: dict[str, Any],
    ) -> None:
        context = "".join(str(part.get("plain_text", "")) for part in rich_text).strip()
        for rule, text, style, start, end in _merge_colored_spans(rich_text, self.color_rules):
            locator = SourceLocator(
                block_id=block_id,
                char_start=start,
                char_end=end,
                metadata=locator_metadata,
            )
            self.captures.append(
                CapturedExcerpt.create(
                    document=self.document,
                    locator=locator,
                    text=text,
                    context_text=context,
                    heading_path=tuple(text for _, text in self.heading_trail),
                    source_style=style,
                    intent=rule.intent,
                    metadata={"notion_block_type": block_type},
                )
            )


def _merge_colored_spans(
    rich_text: list[dict[str, Any]],
    color_rules: dict[str, ColorRule],
) -> list[tuple[ColorRule, str, str, int, int]]:
    merged: list[tuple[ColorRule, str, str, int, int]] = []
    offset = 0
    for part in rich_text:
        plain = str(part.get("plain_text", ""))
        end = offset + len(plain)
        style = str(part.get("annotations", {}).get("color", "default"))
        rule = color_rules.get(style)
        if rule and plain.strip():
            is_continuation = (
                merged
                and merged[-1][0] == rule
                and merged[-1][2] == style
                and merged[-1][4] == offset
            )
            if is_continuation:
                previous_rule, previous_text, previous_style, start, _ = merged[-1]
                merged[-1] = (previous_rule, previous_text + plain, previous_style, start, end)
            else:
                merged.append((rule, plain, style, offset, end))
        offset = end
    return merged


def _block_rich_text(block: dict[str, Any]) -> list[dict[str, Any]]:
    block_type = block.get("type")
    return block.get(str(block_type), {}).get("rich_text", []) if block_type else []


def _block_plain_text(block: dict[str, Any]) -> str:
    return "".join(str(part.get("plain_text", "")) for part in _block_rich_text(block))


def _heading_level(block_type: str) -> int:
    try:
        return int(block_type.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 1


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _dedupe(captures: list[CapturedExcerpt]) -> list[CapturedExcerpt]:
    unique: dict[str, CapturedExcerpt] = {}
    for capture in captures:
        unique.setdefault(capture.capture_id, capture)
    return list(unique.values())
