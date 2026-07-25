"""Notion HTTP client: query prior research notes and publish the daily digest.

HTTP handling follows the pattern in
`family_ceo_review.family_ceo_review.notion_publish.NotionClient` (throttled
httpx requests, retry on 429). This module adds the morning-research-specific
operations: querying prior Markets Research Notes, converting their content
to markdown, creating the new LIBRARY page, and verifying it afterward.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from morning_research.markdown_blocks import chunk_blocks, markdown_to_blocks

logger = structlog.get_logger()

NOTION_BASE = "https://api.notion.com/v1"
API_VERSION = "2022-06-28"
BLOCK_BATCH_SIZE = 100
PRIOR_NOTES_LIMIT = 5

RESOURCE_TYPE_PROPERTY = "Resource Type"
TOPICS_PROPERTY = "Topics"
STATUS_PROPERTY = "Status"
AREA_PROPERTY = "Area"
TITLE_VALUE_RESOURCE_TYPE = "Research Note"
TITLE_VALUE_TOPIC = "Markets"
TITLE_VALUE_STATUS = "Captured"
TITLE_VALUE_AREA = "Job"


class NotionError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotionClient:
    def __init__(
        self,
        token: str,
        *,
        min_interval: float = 0.34,
        area_page_id: str | None = None,
    ) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": API_VERSION,
            "Content-Type": "application/json",
        }
        self._min_interval = min_interval
        self._last_request = 0.0
        self.area_page_id = area_page_id or ""

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retries: int = 4,
    ) -> dict[str, Any]:
        url = f"{NOTION_BASE}{path}"
        attempt = 0
        while True:
            self._throttle()
            with httpx.Client(timeout=60.0) as client:
                response = client.request(
                    method, url, headers=self._headers, json=json, params=params
                )
            self._last_request = time.monotonic()

            if response.status_code == 429 and attempt < retries:
                retry_after = float(response.headers.get("Retry-After", 1))
                time.sleep(retry_after * (attempt + 1))
                attempt += 1
                continue

            if response.status_code >= 400:
                detail = response.text[:800]
                raise NotionError(
                    f"Notion API {response.status_code}: {detail}",
                    status_code=response.status_code,
                )

            if response.status_code == 204:
                return {}
            return response.json()

    # -- Database introspection -------------------------------------------------

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/databases/{database_id}")

    def _property_kind(self, database: dict[str, Any], prop_name: str) -> str | None:
        prop = database.get("properties", {}).get(prop_name)
        return prop.get("type") if prop else None

    # -- Querying prior research notes -------------------------------------------

    def _build_filter(self, database: dict[str, Any]) -> dict[str, Any]:
        """Build a query filter that adapts to select vs multi_select properties."""
        conditions = []

        resource_type_kind = self._property_kind(database, RESOURCE_TYPE_PROPERTY)
        if resource_type_kind == "multi_select":
            conditions.append(
                {
                    "property": RESOURCE_TYPE_PROPERTY,
                    "multi_select": {"contains": TITLE_VALUE_RESOURCE_TYPE},
                }
            )
        elif resource_type_kind == "select":
            conditions.append(
                {"property": RESOURCE_TYPE_PROPERTY, "select": {"equals": TITLE_VALUE_RESOURCE_TYPE}}
            )

        topics_kind = self._property_kind(database, TOPICS_PROPERTY)
        if topics_kind == "multi_select":
            conditions.append(
                {"property": TOPICS_PROPERTY, "multi_select": {"contains": TITLE_VALUE_TOPIC}}
            )
        elif topics_kind == "select":
            conditions.append({"property": TOPICS_PROPERTY, "select": {"equals": TITLE_VALUE_TOPIC}})

        area_kind = self._property_kind(database, AREA_PROPERTY)
        if area_kind == "relation" and self.area_page_id:
            conditions.append(
                {
                    "property": AREA_PROPERTY,
                    "relation": {"contains": self.area_page_id},
                }
            )
        elif area_kind == "multi_select":
            conditions.append({"property": AREA_PROPERTY, "multi_select": {"contains": TITLE_VALUE_AREA}})
        elif area_kind == "select":
            conditions.append({"property": AREA_PROPERTY, "select": {"equals": TITLE_VALUE_AREA}})

        if not conditions:
            return {}
        if len(conditions) == 1:
            return conditions[0]
        return {"and": conditions}

    def query_prior_research_notes(
        self, database_id: str, *, limit: int = PRIOR_NOTES_LIMIT
    ) -> list[dict[str, Any]]:
        """Return up to `limit` most recently edited prior Markets Research Notes."""
        database = self.retrieve_database(database_id)
        filter_obj = self._build_filter(database)

        body: dict[str, Any] = {
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
            "page_size": limit,
        }
        if filter_obj:
            body["filter"] = filter_obj

        response = self._request("POST", f"/databases/{database_id}/query", json=body)
        return response.get("results", [])[:limit]

    # -- Block retrieval / markdown conversion -----------------------------------

    def get_block_children(self, block_id: str) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        cursor = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            response = self._request("GET", f"/blocks/{block_id}/children", params=params)
            children.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        return children

    def blocks_to_markdown(self, block_id: str, *, _depth: int = 0) -> str:
        """Recursively fetch block children and render them as markdown."""
        if _depth > 6:
            return ""
        lines: list[str] = []
        for block in self.get_block_children(block_id):
            lines.append(self._block_to_markdown_line(block))
            if block.get("has_children"):
                nested = self.blocks_to_markdown(block["id"], _depth=_depth + 1)
                if nested:
                    lines.append(nested)
        return "\n".join(line for line in lines if line is not None)

    @staticmethod
    def _rich_text_to_plain(rich_text: list[dict[str, Any]]) -> str:
        return "".join(part.get("plain_text", "") for part in rich_text)

    def _block_to_markdown_line(self, block: dict[str, Any]) -> str:
        block_type = block.get("type", "")
        data = block.get(block_type, {})
        text = self._rich_text_to_plain(data.get("rich_text", [])) if isinstance(data, dict) else ""

        if block_type == "heading_1":
            return f"# {text}"
        if block_type == "heading_2":
            return f"## {text}"
        if block_type == "heading_3":
            return f"### {text}"
        if block_type == "bulleted_list_item":
            return f"- {text}"
        if block_type == "numbered_list_item":
            return f"1. {text}"
        if block_type == "to_do":
            checked = "x" if data.get("checked") else " "
            return f"- [{checked}] {text}"
        if block_type == "quote":
            return f"> {text}"
        if block_type == "divider":
            return "---"
        if block_type == "table_row":
            cells = data.get("cells", [])
            return "| " + " | ".join(self._rich_text_to_plain(cell) for cell in cells) + " |"
        if block_type == "paragraph":
            return text
        return text

    def fetch_prior_notes_to_markdown(
        self, database_id: str, dest_dir: Path, *, limit: int = PRIOR_NOTES_LIMIT
    ) -> list[Path]:
        """Query prior notes and write each one to `dest_dir/{i}_{slug}.md`."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        pages = self.query_prior_research_notes(database_id, limit=limit)
        written: list[Path] = []
        for index, page in enumerate(pages, start=1):
            title = _extract_page_title(page)
            slug = _slugify(title) or page.get("id", f"page-{index}")
            markdown = f"# {title}\n\n" + self.blocks_to_markdown(page["id"])
            path = dest_dir / f"{index}_{slug}.md"
            path.write_text(markdown, encoding="utf-8")
            written.append(path)
            logger.info("Wrote prior note", path=str(path), title=title)
        return written

    # -- Page creation ------------------------------------------------------------

    def build_library_properties(self, database: dict[str, Any], *, title: str) -> dict[str, Any]:
        """Build the LIBRARY page property payload, adapting select vs multi_select."""
        properties: dict[str, Any] = {}

        title_prop_name = next(
            (name for name, prop in database.get("properties", {}).items() if prop.get("type") == "title"),
            "Name",
        )
        properties[title_prop_name] = {"title": [{"type": "text", "text": {"content": title}}]}

        properties.update(
            self._property_payload(database, RESOURCE_TYPE_PROPERTY, TITLE_VALUE_RESOURCE_TYPE)
        )
        properties.update(self._property_payload(database, TOPICS_PROPERTY, TITLE_VALUE_TOPIC))
        properties.update(self._property_payload(database, STATUS_PROPERTY, TITLE_VALUE_STATUS))
        properties.update(self._area_payload(database))

        return properties

    def _area_payload(self, database: dict[str, Any]) -> dict[str, Any]:
        kind = self._property_kind(database, AREA_PROPERTY)
        if kind == "relation":
            if not self.area_page_id:
                logger.warning("Area is a relation but notion_area_page_id is unset; skipping")
                return {}
            return {AREA_PROPERTY: {"relation": [{"id": self.area_page_id}]}}
        if kind in {"select", "multi_select", "rich_text"}:
            return self._property_payload(database, AREA_PROPERTY, TITLE_VALUE_AREA)
        if kind is None:
            logger.warning("Property not found on database; skipping", property=AREA_PROPERTY)
            return {}
        logger.warning("Unsupported Area property kind; skipping", kind=kind)
        return {}

    def _property_payload(
        self, database: dict[str, Any], prop_name: str, value: str
    ) -> dict[str, Any]:
        kind = self._property_kind(database, prop_name)
        if kind == "multi_select":
            return {prop_name: {"multi_select": [{"name": value}]}}
        if kind == "select":
            return {prop_name: {"select": {"name": value}}}
        if kind == "status":
            return {prop_name: {"status": {"name": value}}}
        if kind == "rich_text":
            return {prop_name: {"rich_text": [{"type": "text", "text": {"content": value}}]}}
        if kind is None:
            logger.warning("Property not found on database; skipping", property=prop_name)
            return {}
        logger.warning("Unsupported property kind; skipping", property=prop_name, kind=kind)
        return {}

    def create_page(
        self, *, database_id: str, properties: dict[str, Any], children: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": {"database_id": database_id}, "properties": properties}
        if children:
            body["children"] = children[:BLOCK_BATCH_SIZE]
        return self._request("POST", "/pages", json=body)

    def append_block_children(self, block_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("PATCH", f"/blocks/{block_id}/children", json={"children": children})

    def append_blocks_in_batches(self, page_id: str, children: list[dict[str, Any]]) -> None:
        for batch in chunk_blocks(children, BLOCK_BATCH_SIZE):
            self.append_block_children(page_id, batch)

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        return self._request("GET", f"/pages/{page_id}")

    def publish_draft(self, *, database_id: str, draft_markdown: str, fallback_title: str) -> str:
        """Create a LIBRARY page from `draft_markdown` and verify its properties.

        Returns the created page id. Raises NotionError if verification fails.
        """
        database = self.retrieve_database(database_id)
        title = _extract_title_from_markdown(draft_markdown, fallback=fallback_title)
        properties = self.build_library_properties(database, title=title)

        all_blocks = markdown_to_blocks(draft_markdown)
        first_batch, *rest_batches = chunk_blocks(all_blocks, BLOCK_BATCH_SIZE) or [[]]

        page = self.create_page(database_id=database_id, properties=properties, children=first_batch)
        page_id = page["id"]

        for batch in rest_batches:
            self.append_block_children(page_id, batch)

        self._verify_page(page_id, database)
        logger.info("Published Notion page", page_id=page_id, title=title)
        return page_id

    def _verify_page(self, page_id: str, database: dict[str, Any]) -> None:
        page = self.retrieve_page(page_id)
        properties = page.get("properties", {})
        required = [RESOURCE_TYPE_PROPERTY, TOPICS_PROPERTY, STATUS_PROPERTY, AREA_PROPERTY]
        missing = [name for name in required if name in database.get("properties", {}) and name not in properties]
        if missing:
            raise NotionError(f"Created page is missing required properties: {missing}")


def _extract_page_title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            text = "".join(part.get("plain_text", "") for part in title_parts)
            if text:
                return text
    return page.get("id", "untitled")


def _extract_title_from_markdown(markdown: str, *, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:60]
