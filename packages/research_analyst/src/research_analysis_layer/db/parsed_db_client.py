"""Read-only Supabase/PostgREST client for parser-owned content."""

from __future__ import annotations

import json
from collections.abc import Sequence
from urllib.error import HTTPError, URLError
import urllib.parse
import urllib.request

from research_analysis_layer.models.document_models import (
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
)
from research_analysis_layer.parsed_payload import file_id_from_payload


class ParsedDbClient:
    """Very small read-only client over Supabase PostgREST."""

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _get(
        self,
        table: str,
        params: dict[str, str] | Sequence[tuple[str, str]],
    ) -> list[dict]:
        return self._request_json("GET", table, params=params)

    def _get_optional(
        self,
        table: str,
        params: dict[str, str] | Sequence[tuple[str, str]],
    ) -> list[dict]:
        """GET a table that may not exist yet on older parser projects."""
        try:
            return self._get(table, params)
        except HTTPError as exc:
            if exc.code in {404, 406}:
                return []
            raise
        except (URLError, TimeoutError, json.JSONDecodeError):
            return []

    def _request_json(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | Sequence[tuple[str, str]] | None = None,
        body: object | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> list[dict]:
        query = urllib.parse.urlencode(params or {}, doseq=True, safe="(),.*")
        url = f"{self.base_url}/rest/v1/{table}"
        if query:
            url = f"{url}?{query}"
        payload = None
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read().decode("utf-8")
        if not payload:
            return []
        return json.loads(payload)

    def check_connection(self) -> tuple[bool, str]:
        """Run a lightweight connectivity check."""
        try:
            self._get("parsed_research", {"select": "id", "limit": "1"})
        except Exception as exc:  # pragma: no cover - exercised by CLI
            return False, str(exc)
        return True, "ok"

    def fetch_documents(self, ids: list[int]) -> list[ParsedDocument]:
        """Fetch parsed document rows by research id."""
        if not ids:
            return []
        joined = ",".join(str(item) for item in ids)
        rows = self._get(
            "parsed_research",
            {
                "select": "*",
                "id": f"in.({joined})",
                "order": "id.asc",
            },
        )
        return [self._document_from_row(row) for row in rows]

    def fetch_document_by_hash(self, document_hash: str) -> ParsedDocument | None:
        """Fetch one parsed document by document hash."""
        rows = self._get(
            "parsed_research",
            {
                "select": "*",
                "document_hash": f"eq.{document_hash}",
                "limit": "1",
            },
        )
        if not rows:
            return None
        return self._document_from_row(rows[0])

    def fetch_document_by_file_id(self, file_id: str) -> ParsedDocument | None:
        """Fetch one parsed document by Google Drive file id."""
        rows = self._get(
            "parsed_research",
            {
                "select": "*",
                "document_link": f"like.*{file_id}*",
                "limit": "1",
            },
        )
        if not rows:
            return None
        return self._document_from_row(rows[0])

    def search_documents(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[ParsedDocument]:
        """Search parsed documents by date and source filters."""
        params: list[tuple[str, str]] = [
            ("select", "*"),
            ("order", "source_date.desc,id.desc"),
        ]
        filters: list[str] = []
        if date_from:
            filters.append(f"source_date.gte.{date_from}")
        if date_to:
            filters.append(f"source_date.lte.{date_to}")
        if source:
            escaped = source.replace("%", "").replace("*", "")
            filters.append(f"source.ilike.*{escaped}*")
        if filters:
            params.append(("and", f"({','.join(filters)})"))
        if limit is not None:
            params.append(("limit", str(limit)))
        rows = self._get("parsed_research", params)
        return [self._document_from_row(row) for row in rows]

    def fetch_themes(self, research_ids: list[int]) -> list[ParsedTheme]:
        """Fetch theme rows for the given parsed documents."""
        if not research_ids:
            return []
        joined = ",".join(str(item) for item in research_ids)
        rows = self._get_optional(
            "research_themes",
            {
                "select": "*",
                "research_id": f"in.({joined})",
                "order": "research_id.asc,theme_order.asc",
            },
        )
        return [self._theme_from_row(row) for row in rows]

    def fetch_excerpts(self, theme_ids: list[int]) -> list[ParsedExcerpt]:
        """Fetch excerpt rows for the given theme ids."""
        if not theme_ids:
            return []
        joined = ",".join(str(item) for item in theme_ids)
        rows = self._get_optional(
            "research_theme_excerpts",
            {
                "select": "*",
                "theme_id": f"in.({joined})",
                "order": "theme_id.asc,excerpt_order.asc",
            },
        )
        return [self._excerpt_from_row(row) for row in rows]

    def fetch_spans(self, research_ids: list[int]) -> list[dict]:
        """Fetch substrate span rows. Missing table → empty list."""
        if not research_ids:
            return []
        joined = ",".join(str(item) for item in research_ids)
        return self._get_optional(
            "research_spans",
            {
                "select": "*",
                "research_id": f"in.({joined})",
                "order": "research_id.asc,span_order.asc",
            },
        )

    def fetch_retrieval_chunks(self, research_ids: list[int]) -> list[dict]:
        """Fetch substrate retrieval chunks. Missing table → empty list."""
        if not research_ids:
            return []
        joined = ",".join(str(item) for item in research_ids)
        return self._get_optional(
            "research_retrieval_chunks",
            {
                "select": "*",
                "research_id": f"in.({joined})",
                "order": "research_id.asc,chunk_order.asc",
            },
        )

    def hydrate_document(
        self, document: ParsedDocument, file_id: str | None = None
    ) -> HydratedParsedDocument:
        """Hydrate one parsed document plus themes and excerpts.

        Theme text never comes from `parsed_data.themes` / `parsed_data.parse`.
        Prefer the extraction tables (`research_themes`); if those are empty,
        stand in retrieval chunks + spans until the extraction service lands.
        """
        resolved_file_id = file_id_from_payload(
            document.parsed_data,
            document_link=document.document_link,
            explicit_file_id=file_id,
        )
        themes = self.fetch_themes([document.id])
        if themes:
            excerpts = self.fetch_excerpts([theme.id for theme in themes])
            excerpt_map: dict[int, list[ParsedExcerpt]] = {}
            for excerpt in excerpts:
                excerpt_map.setdefault(excerpt.theme_id, []).append(excerpt)
            hydrated_themes = [
                HydratedTheme(theme=theme, excerpts=excerpt_map.get(theme.id, []))
                for theme in themes
            ]
        else:
            hydrated_themes = self._themes_from_spans_and_chunks(document)
        return HydratedParsedDocument(
            document=document,
            themes=hydrated_themes,
            file_id=resolved_file_id,
        )

    def hydrate_by_file_id(self, file_id: str) -> HydratedParsedDocument | None:
        """Hydrate one document selected from parser state rows."""
        document = self.fetch_document_by_file_id(file_id)
        if document is None:
            return None
        return self.hydrate_document(document, file_id=file_id)

    def hydrate_documents(self, ids: list[int]) -> list[HydratedParsedDocument]:
        """Hydrate parsed documents by research id."""
        documents = self.fetch_documents(ids)
        return [self.hydrate_document(document) for document in documents]

    def hydrate_search(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[HydratedParsedDocument]:
        """Search and hydrate parsed documents for manual backfills."""
        documents = self.search_documents(
            date_from=date_from,
            date_to=date_to,
            source=source,
            limit=limit,
        )
        return [self.hydrate_document(document) for document in documents]

    def search_economic_events(
        self,
        *,
        release_date: str | None = None,
        event_name: str | None = None,
        country: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Search candidate economic event rows for forecast matching."""
        params: list[tuple[str, str]] = [
            ("select", "id,event_name,event_date,country,period,time_ny"),
            ("order", "event_date.asc,time_ny.asc,event_name.asc"),
            ("limit", str(limit)),
        ]
        filters: list[str] = []
        if release_date:
            filters.append(f"event_date.eq.{release_date}")
        if event_name:
            escaped_name = event_name.replace("%", "").replace("*", "")
            filters.append(f"event_name.ilike.*{escaped_name}*")
        if country:
            filters.append(f"country.eq.{country}")
        if filters:
            params.append(("and", f"({','.join(filters)})"))
        return self._get("economic_events", params)

    def insert_economic_event_forecasts(self, payload: list[dict]) -> int:
        """Upload approved forecast rows into the app-facing Supabase table."""
        if not payload:
            return 0
        self._request_json(
            "POST",
            "economic_event_forecasts",
            body=payload,
            extra_headers={"Prefer": "return=minimal"},
        )
        return len(payload)

    def _themes_from_spans_and_chunks(
        self, document: ParsedDocument
    ) -> list[HydratedTheme]:
        """Build theme stand-ins from substrate chunks/spans, not payload keys."""
        chunks = self.fetch_retrieval_chunks([document.id])
        spans = self.fetch_spans([document.id])
        spans_by_key = {
            str(row.get("span_key")): row
            for row in spans
            if row.get("span_key")
        }
        if chunks:
            return [
                self._theme_from_chunk(document, idx, row, spans_by_key)
                for idx, row in enumerate(chunks, start=1)
            ]
        if spans:
            return [
                self._theme_from_span(document, idx, row)
                for idx, row in enumerate(spans, start=1)
            ]
        return []

    @staticmethod
    def _chunk_text(row: dict) -> str:
        for key in ("text", "chunk_text", "content"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _chunk_label(row: dict, fallback_order: int) -> str:
        for key in ("title", "label", "section_name", "heading", "chunk_key"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return f"Chunk {fallback_order}"

    @classmethod
    def _span_keys_for_chunk(cls, row: dict) -> list[str]:
        raw = row.get("span_keys") or row.get("span_key_list") or row.get("span_ids")
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        if isinstance(raw, list):
            return [str(item) for item in raw if item]
        start = row.get("start_span_key") or row.get("span_start_key")
        end = row.get("end_span_key") or row.get("span_end_key")
        keys = [str(item) for item in (start, end) if item]
        return keys

    @classmethod
    def _theme_from_chunk(
        cls,
        document: ParsedDocument,
        order: int,
        row: dict,
        spans_by_key: dict[str, dict],
    ) -> HydratedTheme:
        text = cls._chunk_text(row)
        excerpts: list[ParsedExcerpt] = []
        for excerpt_order, span_key in enumerate(cls._span_keys_for_chunk(row), start=1):
            span = spans_by_key.get(span_key) or {}
            span_text = str(span.get("text") or "").strip()
            if not span_text:
                continue
            excerpts.append(
                ParsedExcerpt(
                    id=excerpt_order,
                    theme_id=order,
                    excerpt_order=excerpt_order,
                    excerpt_text=span_text,
                )
            )
        if not excerpts and text.strip():
            excerpts = [
                ParsedExcerpt(
                    id=1,
                    theme_id=order,
                    excerpt_order=1,
                    excerpt_text=text.strip(),
                )
            ]
        section = row.get("section_name") or row.get("primary_category")
        theme = ParsedTheme(
            id=order,
            research_id=document.id,
            theme_order=int(row.get("chunk_order") or order),
            label=cls._chunk_label(row, order),
            scope=None,
            primary_category=str(section) if section else None,
            relevance=[],
            classification="Description",
            strength="Secondary",
            confidence="Medium",
            evidence_count=len(excerpts),
            mention_count=len(excerpts),
            context=text.strip(),
            directionality=None,
            argument_structure={"source": "retrieval_chunk", "chunk_key": row.get("chunk_key")},
        )
        return HydratedTheme(theme=theme, excerpts=excerpts)

    @staticmethod
    def _theme_from_span(document: ParsedDocument, order: int, row: dict) -> HydratedTheme:
        text = str(row.get("text") or "").strip()
        label = str(row.get("span_type") or row.get("span_key") or f"Span {order}")
        excerpt = ParsedExcerpt(
            id=order,
            theme_id=order,
            excerpt_order=1,
            excerpt_text=text,
        )
        theme = ParsedTheme(
            id=order,
            research_id=document.id,
            theme_order=int(row.get("span_order") or order),
            label=label,
            scope=None,
            primary_category=None,
            relevance=[],
            classification="Description",
            strength="Secondary",
            confidence="Medium",
            evidence_count=1 if text else 0,
            mention_count=1 if text else 0,
            context=text,
            directionality=None,
            argument_structure={"source": "span", "span_key": row.get("span_key")},
        )
        return HydratedTheme(theme=theme, excerpts=[excerpt] if text else [])

    @staticmethod
    def _document_from_row(row: dict) -> ParsedDocument:
        return ParsedDocument(
            id=int(row["id"]),
            document_name=row.get("document_name") or "",
            source=row.get("source"),
            source_date=row.get("source_date"),
            parsed_data=row.get("parsed_data") or {},
            document_title=row.get("document_title"),
            publisher=row.get("publisher"),
            area=row.get("area"),
            region=row.get("region"),
            asset_focus=row.get("asset_focus"),
            document_link=row.get("document_link"),
            theme_count=int(row.get("theme_count") or 0),
            trade_count=int(row.get("trade_count") or 0),
            document_hash=row.get("document_hash"),
        )

    @staticmethod
    def _theme_from_row(row: dict) -> ParsedTheme:
        return ParsedTheme(
            id=int(row["id"]),
            research_id=int(row["research_id"]),
            theme_order=int(row["theme_order"]),
            label=row.get("label") or "",
            scope=row.get("scope"),
            primary_category=row.get("primary_category"),
            relevance=list(row.get("relevance") or []),
            classification=row.get("classification") or "Description",
            strength=row.get("strength") or "Secondary",
            confidence=row.get("confidence") or "Medium",
            evidence_count=int(row.get("evidence_count") or 0),
            mention_count=int(row.get("mention_count") or 0),
            context=row.get("context") or "",
            directionality=row.get("directionality"),
            argument_structure=row.get("argument_structure"),
        )

    @staticmethod
    def _excerpt_from_row(row: dict) -> ParsedExcerpt:
        return ParsedExcerpt(
            id=int(row["id"]),
            theme_id=int(row["theme_id"]),
            excerpt_order=int(row["excerpt_order"]),
            excerpt_text=row.get("excerpt_text") or "",
        )
