"""Live Notion LIBRARY fetch (Research Note only, since last run).

Uses the Notion databases.query API. No secrets are hard-coded — pass a token
via env / constructor. Unit tests use FakeTransport; they never hit Notion.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import urljoin

import httpx

from src.claim_notes.library import (
    LIBRARY_NOTION_DATABASE_ID,
    LIBRARY_NOTION_URL,
    LIBRARY_RESOURCE_TYPE_FILTER,
    LIBRARY_RESOURCE_TYPE_PROPERTY,
    LibraryResearchNote,
)

NOTION_API_BASE = "https://api.notion.com/v1/"
NOTION_VERSION = "2022-06-28"


class NotionTransport(Protocol):
    def post_json(
        self, path: str, *, headers: Mapping[str, str], body: Mapping[str, Any]
    ) -> dict[str, Any]:
        ...


class HttpxNotionTransport:
    """Real Notion HTTP transport (live only when credentials are configured)."""

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self._timeout_s = timeout_s

    def post_json(
        self, path: str, *, headers: Mapping[str, str], body: Mapping[str, Any]
    ) -> dict[str, Any]:
        url = urljoin(NOTION_API_BASE, path.lstrip("/"))
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(url, headers=dict(headers), json=dict(body))
            response.raise_for_status()
            return response.json()


class FakeNotionTransport:
    """Deterministic transport for unit tests — no network."""

    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.pages = list(pages or [])
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self, path: str, *, headers: Mapping[str, str], body: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.calls.append({"path": path, "headers": dict(headers), "body": dict(body)})
        return {"results": list(self.pages), "has_more": False, "next_cursor": None}


class NotionLibraryDigestReader:
    """Query Notion LIBRARY DB: Resource Type = Research Note, saved since last run."""

    def __init__(
        self,
        *,
        token: str | None = None,
        database_id: str = LIBRARY_NOTION_DATABASE_ID,
        resource_type_property: str = LIBRARY_RESOURCE_TYPE_PROPERTY,
        resource_type_value: str = LIBRARY_RESOURCE_TYPE_FILTER,
        transport: NotionTransport | None = None,
    ) -> None:
        self.token = (token or os.getenv("RESEARCH_DISPATCHER_NOTION_TOKEN") or "").strip()
        self.database_id = database_id
        self.resource_type_property = resource_type_property
        self.resource_type_value = resource_type_value
        self.transport = transport or HttpxNotionTransport()

    def list_research_notes(
        self, *, since: datetime | None = None
    ) -> list[LibraryResearchNote]:
        if not self.token and not isinstance(self.transport, FakeNotionTransport):
            raise RuntimeError(
                "RESEARCH_DISPATCHER_NOTION_TOKEN is required for live LIBRARY fetch"
            )
        headers = {
            "Authorization": f"Bearer {self.token or 'test-token'}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        filter_obj = self._build_filter(since)
        body: dict[str, Any] = {"page_size": 100, "filter": filter_obj}
        path = f"databases/{self.database_id}/query"
        results: list[LibraryResearchNote] = []
        while True:
            payload = self.transport.post_json(path, headers=headers, body=body)
            for page in payload.get("results") or []:
                note = self._page_to_note(page)
                if note is not None:
                    results.append(note)
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
            body = {**body, "start_cursor": cursor}
        return results

    def _build_filter(self, since: datetime | None) -> dict[str, Any]:
        resource_clause = {
            "property": self.resource_type_property,
            "select": {"equals": self.resource_type_value},
        }
        if since is None:
            return resource_clause
        stamp = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        since_clause = {
            "timestamp": "last_edited_time",
            "last_edited_time": {"on_or_after": stamp.astimezone(timezone.utc).isoformat()},
        }
        return {"and": [resource_clause, since_clause]}

    def _page_to_note(self, page: Mapping[str, Any]) -> LibraryResearchNote | None:
        props = page.get("properties") or {}
        title = _title_from_props(props) or _optional_str(page.get("id")) or "Untitled"
        note_id = _optional_str(page.get("id"))
        saved_at = _parse_datetime(page.get("last_edited_time") or page.get("created_time"))
        source_date = saved_at.date() if saved_at else None
        summary = _rich_text_prop(props, "Summary") or _rich_text_prop(props, "Notes") or ""
        url = _optional_str(page.get("url")) or (
            f"{LIBRARY_NOTION_URL.rstrip('/')}/{note_id.replace('-', '')}" if note_id else None
        )
        return LibraryResearchNote(
            title=title,
            note_id=note_id,
            source_date=source_date,
            saved_at=saved_at,
            summary=summary,
            url=url,
        )


def _title_from_props(props: Mapping[str, Any]) -> str | None:
    for value in props.values():
        if not isinstance(value, Mapping):
            continue
        if value.get("type") != "title":
            continue
        parts = value.get("title") or []
        text = "".join(
            str(part.get("plain_text") or "") for part in parts if isinstance(part, Mapping)
        ).strip()
        if text:
            return text
    return None


def _rich_text_prop(props: Mapping[str, Any], name: str) -> str:
    value = props.get(name)
    if not isinstance(value, Mapping):
        return ""
    parts = value.get("rich_text") or value.get("title") or []
    return "".join(
        str(part.get("plain_text") or "") for part in parts if isinstance(part, Mapping)
    ).strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
