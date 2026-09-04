"""Helpers for parser-owned `parsed_data` shapes.

`research_parser` is parse + source storage only. After the table wipe,
every new row looks like `{full_text, identity, parse}`.

Do not read:

- `parsed_data.metadata`
- `parsed_data.themes`
- `parsed_data.trades`
- `parsed_data.extraction_stats`

Parser also does not write `research_themes` / excerpts. Hydrate evidence
from `research_document_artifacts`, `research_spans`, and
`research_retrieval_chunks` (join on `parsed_research.id` = `research_id`).
Cite `span_key`, not invented theme labels.

Legacy rows may still have `{full_text, metadata, themes, trades}`.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

PayloadKind = Literal["legacy", "substrate", "empty"]

_DRIVE_FILE_RE = re.compile(r"/d/([A-Za-z0-9_-]{10,})")
_FILE_ID_KEYS = ("document_id", "file_id", "drive_file_id", "google_file_id")


def payload_kind(parsed_data: Any) -> PayloadKind:
    """Classify a `parsed_research.parsed_data` blob."""
    if not isinstance(parsed_data, dict) or not parsed_data:
        return "empty"
    has_identity_or_parse = isinstance(parsed_data.get("identity"), dict) or isinstance(
        parsed_data.get("parse"), dict
    )
    has_legacy_blob = isinstance(parsed_data.get("metadata"), dict) or isinstance(
        parsed_data.get("themes"), list
    )
    if has_identity_or_parse and not has_legacy_blob:
        return "substrate"
    if has_legacy_blob:
        return "legacy"
    if has_identity_or_parse:
        return "substrate"
    return "empty"


def identity_fields(parsed_data: Any) -> dict[str, Any]:
    """Return the parser identity block. Empty for legacy rows."""
    if not isinstance(parsed_data, dict):
        return {}
    identity = parsed_data.get("identity")
    return dict(identity) if isinstance(identity, dict) else {}


def legacy_metadata(parsed_data: Any) -> dict[str, Any]:
    """Return `parsed_data.metadata` for legacy rows only.

    Substrate identity is *not* copied here — callers that need file id
    or house on a new row should prefer the `parsed_research` columns,
    then `identity_fields()`.
    """
    if not isinstance(parsed_data, dict):
        return {}
    metadata = parsed_data.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def parse_fields(parsed_data: Any) -> dict[str, Any]:
    """Return parse artifacts. Never used as a theme/trade source."""
    if not isinstance(parsed_data, dict):
        return {}
    parse = parsed_data.get("parse")
    return dict(parse) if isinstance(parse, dict) else {}


def full_text(parsed_data: Any) -> str:
    """Cleaned body. Prefer spans/chunks in prompts; this is the fallback."""
    if not isinstance(parsed_data, dict):
        return ""
    value = parsed_data.get("full_text")
    return value if isinstance(value, str) else ""


def file_id_from_payload(
    parsed_data: Any,
    *,
    document_link: str | None = None,
    explicit_file_id: str | None = None,
    document_id: str | None = None,
) -> str | None:
    """Resolve the Drive file id.

    Order: caller override → `parsed_research.document_id` column →
    `identity.document_id` → legacy `metadata.document_id` → `document_link`.
    """
    if explicit_file_id:
        return str(explicit_file_id)
    if document_id:
        return str(document_id)

    identity = identity_fields(parsed_data)
    for key in _FILE_ID_KEYS:
        value = identity.get(key)
        if value:
            return str(value)

    metadata = legacy_metadata(parsed_data)
    for key in _FILE_ID_KEYS:
        value = metadata.get(key)
        if value:
            return str(value)

    return file_id_from_document_link(document_link)


def file_id_from_document_link(document_link: str | None) -> str | None:
    """Pull a Google Drive file id out of `parsed_research.document_link`."""
    if not document_link:
        return None
    link = document_link.strip()
    if not link:
        return None
    match = _DRIVE_FILE_RE.search(link)
    if match:
        return match.group(1)
    parsed = urlparse(link)
    query_id = parse_qs(parsed.query).get("id", [None])[0]
    if query_id:
        return str(query_id)
    if "/" not in link and " " not in link and len(link) >= 10:
        return link
    return None


def legacy_trades(parsed_data: Any) -> list[dict[str, Any]]:
    """Trades still live on the legacy blob; substrate rows have none."""
    if not isinstance(parsed_data, dict):
        return []
    trades = parsed_data.get("trades")
    if not isinstance(trades, list):
        return []
    return [item for item in trades if isinstance(item, dict)]
