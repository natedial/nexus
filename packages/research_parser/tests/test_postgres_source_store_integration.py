"""Optional PostgreSQL integration tests for SourceStore."""

import os

import pytest

from src.parser import BlockType, TextBlock
from src.research_memory import ResearchArtifactContext
from src.source import SourceDocument
from src.storage import PostgresSourceStore

DATABASE_URL = os.getenv(
    "RESEARCH_PARSER_DATABASE_URL",
    os.getenv("NEXUS_DATABASE_URL", ""),
)


@pytest.mark.integration
@pytest.mark.skipif(not DATABASE_URL, reason="Set NEXUS_DATABASE_URL to run PostgreSQL tests")
def test_postgres_insert_research_round_trip():
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("DELETE FROM parsed_research WHERE document_id = 'integration-test-doc'")

    store = PostgresSourceStore(DATABASE_URL)
    source = SourceDocument(
        document_id="integration-test-doc",
        document_name="integration.pdf",
        full_text="Integration test paragraph.",
        source="Test Publisher",
        source_date="2026-09-21",
    )
    context = ResearchArtifactContext(
        parse_backend="docling",
        blocks=[
            TextBlock(block_type=BlockType.PARAGRAPH, text="Integration test paragraph.", page=1),
        ],
    )

    row = store.insert_research(source, "integration.pdf", artifact_context=context)
    assert row["document_id"] == "integration-test-doc"

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        spans = conn.execute(
            "SELECT COUNT(*) AS count FROM research_spans WHERE research_id = %s",
            (row["id"],),
        ).fetchone()
        chunks = conn.execute(
            "SELECT COUNT(*) AS count FROM research_retrieval_chunks WHERE research_id = %s",
            (row["id"],),
        ).fetchone()
        assert spans["count"] >= 1
        assert chunks["count"] >= 1

        conn.execute(
            "DELETE FROM parsed_research WHERE document_id = 'integration-test-doc'"
        )
