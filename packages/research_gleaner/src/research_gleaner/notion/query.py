from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class NotionQuery:
    data_source_id: str
    topic: str | None = None
    resource_types: tuple[str, ...] = ()
    since: str | None = None
    title_property: str = "Name"
    topics_property: str = "Topics"
    resource_type_property: str = "Resource Type"


def parse_since(value: str, *, now: datetime | None = None) -> datetime:
    match = re.fullmatch(r"(\d+)(h|d)", value.strip().lower())
    if not match:
        raise ValueError(f"invalid --since value: {value!r}; use 24h or 7d")
    amount = int(match.group(1))
    if amount < 1:
        raise ValueError("--since must be positive")
    delta = timedelta(hours=amount) if match.group(2) == "h" else timedelta(days=amount)
    return (now or datetime.now(UTC)) - delta


def build_filter(query: NotionQuery, *, now: datetime | None = None) -> dict[str, Any] | None:
    clauses: list[dict[str, Any]] = []
    if query.since:
        since = parse_since(query.since, now=now)
        clauses.append(
            {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": since.isoformat()},
            }
        )
    if query.topic:
        clauses.append(
            {
                "property": query.topics_property,
                "multi_select": {"contains": query.topic},
            }
        )
    if query.resource_types:
        clauses.append(
            {
                "or": [
                    {
                        "property": query.resource_type_property,
                        "multi_select": {"contains": resource_type},
                    }
                    for resource_type in query.resource_types
                ]
            }
        )
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"and": clauses}


def query_pages(client: Any, query: NotionQuery) -> list[dict[str, Any]]:
    return client.paginate(
        lambda start_cursor=None: client.query_data_source(
            query.data_source_id,
            filter_body=build_filter(query),
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
            start_cursor=start_cursor,
        )
    )


def page_title(page: dict[str, Any], title_property: str) -> str:
    properties = page.get("properties", {})
    preferred = properties.get(title_property, {})
    if preferred.get("type") == "title":
        return _plain_text(preferred.get("title", [])) or "Untitled"
    for prop in properties.values():
        if prop.get("type") == "title":
            return _plain_text(prop.get("title", [])) or "Untitled"
    return "Untitled"


def page_multi_select(page: dict[str, Any], property_name: str) -> tuple[str, ...]:
    prop = page.get("properties", {}).get(property_name, {})
    return tuple(
        str(item.get("name", "")) for item in prop.get("multi_select", []) if item.get("name")
    )


def _plain_text(rich_text: list[dict[str, Any]]) -> str:
    return "".join(str(part.get("plain_text", "")) for part in rich_text)
