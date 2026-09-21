"""PostgreSQL read client for parser-owned content."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from research_analysis_layer.db.parsed_db_client import ParsedDbClient
from research_analysis_layer.models.document_models import (
    HydratedParsedDocument,
    ParsedDocument,
    ParsedTheme,
)


class PostgresParsedDbClient(ParsedDbClient):
    """Read parser tables from the consolidated Nexus PostgreSQL instance."""

    def __init__(self, database_url: str, timeout_seconds: int = 30):
        self.database_url = database_url
        self.timeout_seconds = timeout_seconds
        self.base_url = ""
        self.api_key = ""

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=self.timeout_seconds,
        )

    def _fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _fetch_optional(
        self, query: str, params: tuple[Any, ...] = ()
    ) -> list[dict]:
        try:
            return self._fetch_all(query, params)
        except psycopg.errors.UndefinedTable:
            return []

    def check_connection(self) -> tuple[bool, str]:
        try:
            self._fetch_all("SELECT id FROM parsed_research LIMIT 1")
        except Exception as exc:  # pragma: no cover - exercised by CLI
            return False, str(exc)
        return True, "ok"

    def fetch_documents(self, ids: list[int]) -> list[ParsedDocument]:
        if not ids:
            return []
        placeholders = ", ".join(["%s"] * len(ids))
        rows = self._fetch_all(
            f"SELECT * FROM parsed_research WHERE id IN ({placeholders}) ORDER BY id ASC",
            tuple(ids),
        )
        return [self._document_from_row(row) for row in rows]

    def fetch_document_by_hash(self, document_hash: str) -> ParsedDocument | None:
        rows = self._fetch_all(
            "SELECT * FROM parsed_research WHERE document_hash = %s LIMIT 1",
            (document_hash,),
        )
        if not rows:
            return None
        return self._document_from_row(rows[0])

    def fetch_document_by_file_id(self, file_id: str) -> ParsedDocument | None:
        rows = self._fetch_all(
            "SELECT * FROM parsed_research WHERE document_id = %s LIMIT 1",
            (file_id,),
        )
        if not rows:
            rows = self._fetch_all(
                "SELECT * FROM parsed_research WHERE document_link LIKE %s LIMIT 1",
                (f"%{file_id}%",),
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
        clauses = ["1=1"]
        params: list[Any] = []
        if date_from:
            clauses.append("source_date >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("source_date <= %s")
            params.append(date_to)
        if source:
            clauses.append("source ILIKE %s")
            params.append(f"%{source}%")
        query = (
            "SELECT * FROM parsed_research WHERE "
            + " AND ".join(clauses)
            + " ORDER BY source_date DESC NULLS LAST, id DESC"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        rows = self._fetch_all(query, tuple(params))
        return [self._document_from_row(row) for row in rows]

    def fetch_themes(self, research_ids: list[int]) -> list[ParsedTheme]:
        if not research_ids:
            return []
        placeholders = ", ".join(["%s"] * len(research_ids))
        rows = self._fetch_optional(
            f"""
            SELECT * FROM research_themes
            WHERE research_id IN ({placeholders})
            ORDER BY research_id ASC, theme_order ASC
            """,
            tuple(research_ids),
        )
        return [self._theme_from_row(row) for row in rows]

    def fetch_excerpts(self, theme_ids: list[int]) -> list:
        if not theme_ids:
            return []
        placeholders = ", ".join(["%s"] * len(theme_ids))
        rows = self._fetch_optional(
            f"""
            SELECT * FROM research_theme_excerpts
            WHERE theme_id IN ({placeholders})
            ORDER BY theme_id ASC, excerpt_order ASC
            """,
            tuple(theme_ids),
        )
        return [self._excerpt_from_row(row) for row in rows]

    def fetch_spans(self, research_ids: list[int]) -> list[dict]:
        if not research_ids:
            return []
        placeholders = ", ".join(["%s"] * len(research_ids))
        return self._fetch_optional(
            f"""
            SELECT * FROM research_spans
            WHERE research_id IN ({placeholders})
            ORDER BY research_id ASC, span_order ASC
            """,
            tuple(research_ids),
        )

    def fetch_retrieval_chunks(self, research_ids: list[int]) -> list[dict]:
        if not research_ids:
            return []
        placeholders = ", ".join(["%s"] * len(research_ids))
        return self._fetch_optional(
            f"""
            SELECT * FROM research_retrieval_chunks
            WHERE research_id IN ({placeholders})
            ORDER BY research_id ASC, chunk_order ASC
            """,
            tuple(research_ids),
        )

    def fetch_document_artifacts(self, research_ids: list[int]) -> list[dict]:
        if not research_ids:
            return []
        placeholders = ", ".join(["%s"] * len(research_ids))
        return self._fetch_optional(
            f"""
            SELECT * FROM research_document_artifacts
            WHERE research_id IN ({placeholders})
            LIMIT %s
            """,
            tuple(research_ids) + (max(1, len(research_ids)),),
        )

    def search_economic_events(
        self,
        *,
        release_date: str | None = None,
        event_name: str | None = None,
        country: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list[Any] = []
        if release_date:
            clauses.append("event_date = %s")
            params.append(release_date)
        if event_name:
            clauses.append("event_name ILIKE %s")
            params.append(f"%{event_name}%")
        if country:
            clauses.append("country = %s")
            params.append(country)
        params.append(limit)
        return self._fetch_optional(
            f"""
            SELECT id, event_name, event_date, country, period, time_ny
            FROM economic_events
            WHERE {" AND ".join(clauses)}
            ORDER BY event_date ASC NULLS LAST, time_ny ASC NULLS LAST, event_name ASC
            LIMIT %s
            """,
            tuple(params),
        )

    def insert_economic_event_forecasts(self, payload: list[dict]) -> int:
        if not payload:
            return 0
        columns = sorted(payload[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        column_sql = ", ".join(columns)
        query = (
            f"INSERT INTO economic_event_forecasts ({column_sql}) "
            f"VALUES ({placeholders})"
        )
        with self._connect() as conn:
            with conn.transaction():
                for row in payload:
                    conn.execute(query, tuple(row[column] for column in columns))
        return len(payload)


class PostgresCalendarDbClient(PostgresParsedDbClient):
    """PostgreSQL calendar matching over economic_events or release_dates."""

    def __init__(
        self,
        database_url: str,
        *,
        timeout_seconds: int = 30,
        match_source: str = "economic_events",
        source_name: str = "economic_events",
    ):
        super().__init__(database_url, timeout_seconds=timeout_seconds)
        self.match_source = match_source
        self.source_name = source_name

    def check_connection(self) -> tuple[bool, str]:
        table = "release_dates" if self.match_source == "release_dates" else "economic_events"
        try:
            self._fetch_optional(f"SELECT id FROM {table} LIMIT 1")
        except Exception as exc:  # pragma: no cover - exercised by CLI
            return False, str(exc)
        return True, "ok"

    def search_calendar_matches(
        self,
        *,
        release_date: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        if self.match_source == "release_dates":
            return self._search_release_dates(
                release_date=release_date,
                country=country,
                limit=limit,
            )
        return self.search_economic_events(
            release_date=release_date,
            country=country,
            limit=limit,
        )

    def _search_release_dates(
        self,
        *,
        release_date: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list[Any] = []
        if release_date:
            clauses.append("release_date = %s")
            params.append(release_date)
        params.append(limit)
        date_rows = self._fetch_optional(
            f"""
            SELECT id, release_id, release_date
            FROM release_dates
            WHERE {" AND ".join(clauses)}
            ORDER BY release_date ASC NULLS LAST, release_id ASC
            LIMIT %s
            """,
            tuple(params),
        )
        if not date_rows:
            return []

        release_ids = sorted(
            {
                int(row["release_id"])
                for row in date_rows
                if row.get("release_id") is not None
            }
        )
        if not release_ids:
            return []

        placeholders = ", ".join(["%s"] * len(release_ids))
        release_rows = self._fetch_optional(
            f"""
            SELECT id, name, fred_release_id, link, press_release
            FROM releases
            WHERE id IN ({placeholders})
            """,
            tuple(release_ids),
        )
        releases_by_id = {
            int(row["id"]): row for row in release_rows if row.get("id") is not None
        }

        normalized_rows: list[dict] = []
        for row in date_rows:
            release_id = row.get("release_id")
            if release_id is None:
                continue
            release = releases_by_id.get(int(release_id))
            release_name = (
                str(release.get("name"))
                if release and release.get("name") is not None
                else f"Release {release_id}"
            )
            normalized_rows.append(
                {
                    "id": str(row.get("id") or ""),
                    "calendar_release_id": str(row.get("id") or ""),
                    "calendar_source": self.source_name,
                    "event_name": release_name,
                    "event_date": row.get("release_date"),
                    "country": country or "US",
                    "period": None,
                    "time_ny": None,
                    "fred_release_id": (
                        release.get("fred_release_id") if release is not None else None
                    ),
                }
            )
        return normalized_rows
