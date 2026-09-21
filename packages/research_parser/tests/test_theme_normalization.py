from __future__ import annotations

from pathlib import Path

from src.source import SourceDocument
from src.storage.source_store import compute_document_hash
from tests.fake_source_store import FakeSourceStore, _FakePostgrestClient


def test_insert_research_reuses_existing_row_and_preserves_themes():
    fake_backend = _FakePostgrestClient()
    client = FakeSourceStore(fake_backend)

    source = SourceDocument(
        document_id="drive-ms",
        document_name="ms-note.pdf",
        full_text="Cleaned document text",
        source="Morgan Stanley",
        source_date="2026-03-21",
        document_link="https://example.com/ms",
        document_uri="gdrive://drive-ms",
    )

    document_hash = compute_document_hash(source.full_text)
    fake_backend.tables["parsed_research"].append(
        {
            "id": 7,
            "document_id": "drive-ms",
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
            "document_hash": "old-markdown-hash",
            "index_status": "indexed",
            "indexed_at": "2026-03-20T12:00:00Z",
            "index_error": "old error",
            "index_version": "old-version",
            "indexing_batch_id": 123,
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

    stored = client.insert_research(source, "ms-note.pdf")

    assert stored["id"] == 7
    assert len(fake_backend.tables["parsed_research"]) == 1
    row = fake_backend.tables["parsed_research"][0]
    assert row["theme_count"] == 99
    assert row["trade_count"] == 99
    assert row["document_hash"] == document_hash
    assert row["index_status"] == "indexed"
    assert row["indexed_at"] == "2026-03-20T12:00:00Z"
    assert row["index_error"] == "old error"
    assert row["index_version"] == "old-version"
    assert row["indexing_batch_id"] == 123
    assert row["publisher"] == "Old publisher"
    assert row["document_title"] == "ms-note"
    assert "themes" not in row["parsed_data"]
    assert "trades" not in row["parsed_data"]

    themes = fake_backend.tables["research_themes"]
    assert len(themes) == 1
    assert themes[0]["research_id"] == 7
    assert themes[0]["label"] == "Old theme"

    excerpts = fake_backend.tables["research_theme_excerpts"]
    assert len(excerpts) == 1
    assert excerpts[0]["excerpt_text"] == "Old excerpt"


def test_insert_research_requires_document_id():
    fake_backend = _FakePostgrestClient()
    client = FakeSourceStore(fake_backend)

    source = SourceDocument(
        document_id="",
        document_name="ms-note.pdf",
        full_text="Cleaned document text",
        source="Morgan Stanley",
        source_date="2026-03-21",
    )

    try:
        client.insert_research(source, "ms-note.pdf")
    except ValueError as exc:
        assert "document_id is required" in str(exc)
    else:
        raise AssertionError("insert_research should require document_id")


def test_document_identity_migration_uses_plain_unique_index():
    """The parser upsert conflict target must match a real unique index."""
    migration = Path("migrations/005_parsed_research_document_id_identity.sql").read_text()

    assert "DROP INDEX IF EXISTS idx_parsed_research_document_identity;" in migration
    assert "CREATE UNIQUE INDEX idx_parsed_research_document_identity" in migration
    assert "ON parsed_research(document_id);" in migration
    assert "ADD COLUMN IF NOT EXISTS document_id TEXT NULL" in migration
    assert "parsed_data->'metadata'->>'document_id'" in migration
    create_index_sql = migration.split(
        "CREATE UNIQUE INDEX idx_parsed_research_document_identity", 1
    )[1]
    assert "WHERE document_id IS NOT NULL" not in create_index_sql
