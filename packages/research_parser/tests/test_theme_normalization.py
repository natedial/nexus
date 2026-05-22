from __future__ import annotations

from pathlib import Path

from scripts.backfill_theme_normalization import (
    _extract_metadata_from_parsed_data,
    _extract_themes_from_parsed_data,
    _process_batch,
)
from src.extraction.models import Excerpt, ExtractionResult, Metadata, Theme
from src.storage.supabase import SupabaseClient, _compute_document_hash


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client: _FakeSupabase, name: str):
        self._client = client
        self._name = name
        self._action = "select"
        self._filters: list[tuple[str, str, object]] = []
        self._payload = None
        self._limit: int | None = None
        self._on_conflict: list[str] = []

    def select(self, _columns: str):
        self._action = "select"
        return self

    def eq(self, column: str, value):
        self._filters.append(("eq", column, value))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def update(self, payload: dict):
        self._action = "update"
        self._payload = payload
        return self

    def insert(self, payload: dict):
        self._action = "insert"
        self._payload = payload
        return self

    def upsert(self, payload: dict, on_conflict: str):
        self._action = "upsert"
        self._payload = payload
        self._on_conflict = [item.strip() for item in on_conflict.split(",") if item]
        return self

    def delete(self):
        self._action = "delete"
        return self

    def execute(self):
        rows = self._client.tables.setdefault(self._name, [])
        filtered = [row for row in rows if self._matches(row)]
        if self._limit is not None:
            filtered = filtered[: self._limit]

        if self._action == "select":
            return _FakeResponse([dict(row) for row in filtered])

        if self._action == "update":
            updated = []
            for row in filtered:
                row.update(self._payload)
                updated.append(dict(row))
            return _FakeResponse(updated)

        if self._action == "insert":
            row = dict(self._payload)
            if "id" not in row:
                row["id"] = self._client.next_ids.setdefault(self._name, 1)
                self._client.next_ids[self._name] += 1
            rows.append(row)
            return _FakeResponse([dict(row)])

        if self._action == "upsert":
            for row in rows:
                if all(row.get(column) == self._payload.get(column) for column in self._on_conflict):
                    row.update(self._payload)
                    return _FakeResponse([dict(row)])

            row = dict(self._payload)
            if "id" not in row:
                row["id"] = self._client.next_ids.setdefault(self._name, 1)
                self._client.next_ids[self._name] += 1
            rows.append(row)
            return _FakeResponse([dict(row)])

        if self._action == "delete":
            kept = [row for row in rows if not self._matches(row)]
            self._client.tables[self._name] = kept
            deleted_count = len(rows) - len(kept)
            if self._name == "research_themes" and deleted_count:
                valid_theme_ids = {row["id"] for row in kept}
                excerpts = self._client.tables.setdefault("research_theme_excerpts", [])
                self._client.tables["research_theme_excerpts"] = [
                    row for row in excerpts if row["theme_id"] in valid_theme_ids
                ]
            return _FakeResponse([])

        raise AssertionError(f"Unsupported action: {self._action}")

    def _matches(self, row: dict) -> bool:
        for op, column, value in self._filters:
            if op == "eq" and row.get(column) != value:
                return False
        return True


class _FakeSupabase:
    def __init__(self):
        self.tables = {
            "parsed_research": [],
            "research_themes": [],
            "research_theme_excerpts": [],
        }
        self.next_ids = {
            "parsed_research": 1,
            "research_themes": 1,
            "research_theme_excerpts": 1,
        }

    def table(self, name: str):
        return _FakeTable(self, name)


def test_extract_metadata_from_parsed_data_includes_source():
    parsed_data = {
        "metadata": {
            "source": "Goldman Sachs",
            "publisher": "GS",
            "area": "Macro",
            "region": "US",
            "asset_focus": "rates",
            "document_link": "https://example.com/report",
        }
    }

    metadata = _extract_metadata_from_parsed_data(parsed_data)

    assert metadata["source"] == "Goldman Sachs"
    assert metadata["publisher"] == "GS"
    assert metadata["area"] == "Macro"
    assert metadata["region"] == "US"
    assert metadata["asset_focus"] == "rates"
    assert metadata["document_link"] == "https://example.com/report"


def test_extract_themes_from_parsed_data_normalizes_string_relevance():
    parsed_data = {
        "themes": [
            {
                "label": "Front-end duration",
                "relevance": "Rates",
                "excerpts": [{"text": "Own the front end."}],
            }
        ]
    }

    themes = _extract_themes_from_parsed_data(parsed_data)

    assert len(themes) == 1
    assert themes[0]["relevance"] == ["Rates"]


def test_insert_research_reuses_existing_row_and_replaces_normalized_children():
    fake_backend = _FakeSupabase()
    client = SupabaseClient.__new__(SupabaseClient)
    client._client = fake_backend

    result = ExtractionResult(
        metadata=Metadata(
            source="Morgan Stanley",
            source_date="2026-03-21",
            area="Macro",
            region="US",
            asset_focus="rates",
            publisher="Morgan Stanley",
            document_link="https://example.com/ms",
        ),
        themes=[
            Theme(
                label="Curve steepening",
                excerpts=[Excerpt(text="Front-end pressure shifts to the belly.")],
                relevance=["Rates"],
                mention_count=1,
                strength="Primary",
                confidence="High",
                context="Pressure shifts from front-end to the belly of the curve.",
            )
        ],
        trades=[],
        full_text="Cleaned document text",
    )

    document_hash = _compute_document_hash(result.full_text)
    fake_backend.tables["parsed_research"].append(
        {
            "id": 7,
            "parsed_data": {"old": True},
            "source_date": "2026-03-20",
            "source": "Morgan Stanley",
            "document_name": "ms-note.pdf",
            "document_title": "Old title",
            "publisher": "Old publisher",
            "area": "Old area",
            "region": "Old region",
            "asset_focus": "Old focus",
            "document_link": None,
            "theme_count": 99,
            "trade_count": 99,
            "document_hash": document_hash,
        }
    )
    fake_backend.next_ids["parsed_research"] = 8
    fake_backend.tables["research_themes"].append(
        {
            "id": 3,
            "research_id": 7,
            "theme_order": 1,
            "label": "Old theme",
        }
    )
    fake_backend.tables["research_theme_excerpts"].append(
        {
            "id": 5,
            "theme_id": 3,
            "excerpt_order": 1,
            "excerpt_text": "Old excerpt",
        }
    )
    fake_backend.next_ids["research_themes"] = 4
    fake_backend.next_ids["research_theme_excerpts"] = 6

    stored = client.insert_research(result, "ms-note.pdf")

    assert stored["id"] == 7
    assert len(fake_backend.tables["parsed_research"]) == 1
    assert fake_backend.tables["parsed_research"][0]["theme_count"] == 1
    assert (
        fake_backend.tables["parsed_research"][0]["document_title"]
        == "Analysis of Morgan Stanley"
    )

    themes = fake_backend.tables["research_themes"]
    assert len(themes) == 1
    assert themes[0]["research_id"] == 7
    assert themes[0]["label"] == "Curve steepening"

    excerpts = fake_backend.tables["research_theme_excerpts"]
    assert len(excerpts) == 1
    assert excerpts[0]["excerpt_text"] == "Front-end pressure shifts to the belly."


def test_backfill_replaces_partial_existing_normalized_rows():
    fake_backend = _FakeSupabase()
    fake_backend.tables["parsed_research"].append(
        {
            "id": 11,
            "source": "J.P. Morgan",
            "source_date": "2026-03-22",
            "document_name": "jpm-note.pdf",
            "parsed_data": {
                "metadata": {
                    "source": "J.P. Morgan",
                    "publisher": "J.P. Morgan",
                    "area": "USD",
                    "region": "US",
                    "asset_focus": "rates",
                    "document_link": "https://example.com/jpm",
                },
                "themes": [
                    {
                        "label": "Energy shock",
                        "excerpts": [{"text": "Oil shock drives the front end."}],
                        "relevance": ["Rates", "Macro"],
                        "classification": "Forecast",
                        "strength": "Primary",
                        "confidence": "High",
                        "context": "Energy shock pushes rates volatility higher.",
                    }
                ],
                "trades": [{"text": "Own gamma"}],
                "full_text": "Normalized document body",
            },
        }
    )
    fake_backend.tables["research_themes"].append(
        {
            "id": 20,
            "research_id": 11,
            "theme_order": 1,
            "label": "Stale partial theme",
        }
    )
    fake_backend.tables["research_theme_excerpts"].append(
        {
            "id": 30,
            "theme_id": 20,
            "excerpt_order": 1,
            "excerpt_text": "Stale excerpt",
        }
    )
    fake_backend.next_ids["research_themes"] = 21
    fake_backend.next_ids["research_theme_excerpts"] = 31

    processed, skipped, errors = _process_batch(
        fake_backend,
        [fake_backend.tables["parsed_research"][0]],
    )

    assert processed == 1
    assert skipped == 0
    assert errors == 0

    research_row = fake_backend.tables["parsed_research"][0]
    assert research_row["theme_count"] == 1
    assert research_row["trade_count"] == 1
    assert research_row["document_hash"] == _compute_document_hash("Normalized document body")

    themes = fake_backend.tables["research_themes"]
    assert len(themes) == 1
    assert themes[0]["research_id"] == 11
    assert themes[0]["label"] == "Energy shock"

    excerpts = fake_backend.tables["research_theme_excerpts"]
    assert len(excerpts) == 1
    assert excerpts[0]["excerpt_text"] == "Oil shock drives the front end."


def test_backfill_clears_existing_normalized_rows_when_source_has_no_themes():
    fake_backend = _FakeSupabase()
    fake_backend.tables["parsed_research"].append(
        {
            "id": 12,
            "source": "Barclays",
            "source_date": "2026-03-22",
            "document_name": "barclays-note.pdf",
            "parsed_data": {
                "metadata": {
                    "source": "Barclays",
                    "publisher": "Barclays",
                },
                "themes": [],
                "trades": [],
                "full_text": "Legacy note without stored themes",
            },
        }
    )
    fake_backend.tables["research_themes"].append(
        {
            "id": 40,
            "research_id": 12,
            "theme_order": 1,
            "label": "Should be removed",
        }
    )
    fake_backend.tables["research_theme_excerpts"].append(
        {
            "id": 50,
            "theme_id": 40,
            "excerpt_order": 1,
            "excerpt_text": "Should also be removed",
        }
    )

    processed, skipped, errors = _process_batch(
        fake_backend,
        [fake_backend.tables["parsed_research"][0]],
    )

    assert processed == 1
    assert skipped == 0
    assert errors == 0
    assert fake_backend.tables["research_themes"] == []
    assert fake_backend.tables["research_theme_excerpts"] == []

    research_row = fake_backend.tables["parsed_research"][0]
    assert research_row["theme_count"] == 0
    assert research_row["trade_count"] == 0
    assert research_row["document_hash"] == _compute_document_hash(
        "Legacy note without stored themes"
    )


def test_document_identity_migration_uses_plain_unique_index():
    """The parser upsert conflict target must match a real unique index."""
    migration = Path("migrations/003_parsed_research_document_identity.sql").read_text()

    assert "DROP INDEX IF EXISTS idx_parsed_research_document_identity;" in migration
    assert "CREATE UNIQUE INDEX idx_parsed_research_document_identity" in migration
    assert "ON parsed_research(document_hash, document_name, source);" in migration
    create_index_sql = migration.split(
        "CREATE UNIQUE INDEX idx_parsed_research_document_identity", 1
    )[1]
    assert "WHERE document_hash IS NOT NULL" not in create_index_sql
