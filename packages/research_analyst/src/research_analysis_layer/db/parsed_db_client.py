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
    ParsedDocumentArtifacts,
    ParsedExcerpt,
    ParsedRetrievalChunk,
    ParsedSpan,
    ParsedTheme,
)
from research_analysis_layer.parsed_payload import file_id_from_payload, parse_fields


def coerce_optional_date(value: object) -> str | None:
    """Normalize Postgres DATE / Python date values to ISO strings for JSON."""
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    if isinstance(value, str):
        return value
    return str(value)


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
        """Fetch one parsed document by Google Drive file id.

        Prefer the `document_id` upsert key. Fall back to `document_link`
        for rows written before that column existed.
        """
        rows: list[dict] = []
        try:
            rows = self._get(
                "parsed_research",
                {
                    "select": "*",
                    "document_id": f"eq.{file_id}",
                    "limit": "1",
                },
            )
        except HTTPError as exc:
            if exc.code not in {400, 404, 406}:
                raise
        if not rows:
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
        """Fetch parser span rows. Missing table → empty list."""
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
        """Fetch parser retrieval chunks. Missing table → empty list."""
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

    def fetch_document_artifacts(self, research_ids: list[int]) -> list[dict]:
        """Fetch parser artifact rows. Missing table → empty list."""
        if not research_ids:
            return []
        joined = ",".join(str(item) for item in research_ids)
        return self._get_optional(
            "research_document_artifacts",
            {
                "select": "*",
                "research_id": f"in.({joined})",
                "limit": str(max(1, len(research_ids))),
            },
        )

    def hydrate_document(
        self, document: ParsedDocument, file_id: str | None = None
    ) -> HydratedParsedDocument:
        """Hydrate one parsed document.

        Always attach artifacts, spans, and retrieval chunks. Extraction
        themes are an optional overlay — never synthesized from chunks.
        Never read `parsed_data.themes` / `parsed_data.parse` as themes.
        """
        resolved_file_id = file_id_from_payload(
            document.parsed_data,
            document_link=document.document_link,
            explicit_file_id=file_id,
            document_id=document.document_id,
        )
        theme_rows = self.fetch_themes([document.id])
        hydrated_themes: list[HydratedTheme] = []
        if theme_rows:
            excerpts = self.fetch_excerpts([theme.id for theme in theme_rows])
            excerpt_map: dict[int, list[ParsedExcerpt]] = {}
            for excerpt in excerpts:
                excerpt_map.setdefault(excerpt.theme_id, []).append(excerpt)
            hydrated_themes = [
                HydratedTheme(theme=theme, excerpts=excerpt_map.get(theme.id, []))
                for theme in theme_rows
            ]
        span_rows = self.fetch_spans([document.id])
        chunk_rows = self.fetch_retrieval_chunks([document.id])
        artifact_rows = self.fetch_document_artifacts([document.id])
        return HydratedParsedDocument(
            document=document,
            themes=hydrated_themes,
            file_id=resolved_file_id,
            spans=[self._span_from_row(row) for row in span_rows],
            retrieval_chunks=[self._retrieval_chunk_from_row(row) for row in chunk_rows],
            artifacts=self._artifacts_for(document, artifact_rows),
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

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _str_list(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    return [stripped]
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if item]
            return [stripped]
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []

    @classmethod
    def _span_keys_for_chunk(cls, row: dict) -> list[str]:
        raw = row.get("span_keys") or row.get("span_key_list") or row.get("span_ids")
        keys = cls._str_list(raw)
        if keys:
            return keys
        start = row.get("start_span_key") or row.get("span_start_key")
        end = row.get("end_span_key") or row.get("span_end_key")
        return [str(item) for item in (start, end) if item]

    @staticmethod
    def _chunk_text(row: dict) -> str:
        for key in ("chunk_text", "text", "content"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    @staticmethod
    def _bbox(value: object) -> dict | None:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list) and len(value) == 4:
            return {"x0": value[0], "y0": value[1], "x1": value[2], "y1": value[3]}
        return None

    @classmethod
    def _span_from_row(cls, row: dict) -> ParsedSpan:
        span_id = row.get("span_id") or row.get("id")
        heading = row.get("heading_path") or row.get("heading")
        return ParsedSpan(
            span_key=str(row.get("span_key") or span_id or ""),
            text=str(row.get("text") or ""),
            span_kind=str(row.get("span_kind") or row.get("span_type") or "") or None,
            page_start=cls._optional_int(
                row.get("page_start") if row.get("page_start") is not None else row.get("page")
            ),
            page_end=cls._optional_int(row.get("page_end")),
            bbox=cls._bbox(row.get("bbox")),
            heading_path=cls._str_list(heading),
            span_id=str(span_id) if span_id is not None else None,
            span_order=cls._optional_int(row.get("span_order")),
        )

    @classmethod
    def _retrieval_chunk_from_row(cls, row: dict) -> ParsedRetrievalChunk:
        chunk_id = row.get("chunk_id") or row.get("id")
        chunk_key = row.get("chunk_key") or chunk_id
        heading = row.get("heading_path") or row.get("heading")
        return ParsedRetrievalChunk(
            chunk_key=str(chunk_key or ""),
            chunk_text=cls._chunk_text(row),
            span_keys=cls._span_keys_for_chunk(row),
            page_start=cls._optional_int(row.get("page_start")),
            page_end=cls._optional_int(row.get("page_end")),
            token_count=cls._optional_int(row.get("token_count")),
            heading_path=cls._str_list(heading),
            chunk_id=str(chunk_id) if chunk_id is not None else None,
            chunk_order=cls._optional_int(row.get("chunk_order")),
        )

    @classmethod
    def _artifacts_from_row(cls, row: dict) -> ParsedDocumentArtifacts:
        manifest = row.get("artifact_manifest")
        if not isinstance(manifest, dict):
            manifest = None
        blocks_path = row.get("blocks_path")
        if not blocks_path and manifest:
            blocks_path = manifest.get("blocks_path")
        score = row.get("confidence_score")
        if score is None:
            score = row.get("confidence")
        return ParsedDocumentArtifacts(
            parse_backend=row.get("parse_backend") or row.get("backend"),
            parser_version=row.get("parser_version"),
            confidence_score=cls._optional_float(score),
            confidence_status=row.get("confidence_status"),
            raw_markdown_path=row.get("raw_markdown_path"),
            clean_text_path=row.get("clean_text_path"),
            blocks_path=blocks_path,
            artifact_manifest=manifest,
        )

    @classmethod
    def _artifacts_for(
        cls, document: ParsedDocument, rows: list[dict]
    ) -> ParsedDocumentArtifacts | None:
        if rows:
            return cls._artifacts_from_row(rows[0])
        parse = parse_fields(document.parsed_data)
        if not parse:
            return None
        score = parse.get("confidence_score")
        if score is None:
            score = parse.get("confidence")
        return ParsedDocumentArtifacts(
            parse_backend=parse.get("backend"),
            parser_version=parse.get("parser_version"),
            confidence_score=cls._optional_float(score),
            confidence_status=parse.get("confidence_status"),
            raw_markdown_path=parse.get("raw_markdown_path"),
            clean_text_path=parse.get("clean_text_path"),
            blocks_path=parse.get("blocks_path"),
            artifact_manifest=parse.get("artifact_manifest")
            if isinstance(parse.get("artifact_manifest"), dict)
            else None,
        )

    @staticmethod
    def _document_from_row(row: dict) -> ParsedDocument:
        return ParsedDocument(
            id=int(row["id"]),
            document_name=row.get("document_name") or "",
            source=row.get("source"),
            source_date=coerce_optional_date(row.get("source_date")),
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
            document_id=row.get("document_id"),
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
