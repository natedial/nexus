from pathlib import Path

MIGRATION = Path("migrations/004_research_memory_substrate.sql")


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_research_memory_migration_creates_tables_in_dependency_order():
    sql = _migration_sql()
    expected_order = [
        "CREATE TABLE IF NOT EXISTS research_document_artifacts",
        "CREATE TABLE IF NOT EXISTS research_spans",
        "CREATE TABLE IF NOT EXISTS research_retrieval_chunks",
        "CREATE TABLE IF NOT EXISTS research_evidence_units",
        "CREATE TABLE IF NOT EXISTS research_entities",
        "CREATE TABLE IF NOT EXISTS research_claims",
        "CREATE TABLE IF NOT EXISTS research_claim_evidence",
        "CREATE TABLE IF NOT EXISTS research_relations",
        "CREATE TABLE IF NOT EXISTS research_memory_events",
    ]

    positions = [sql.index(statement) for statement in expected_order]

    assert positions == sorted(positions)


def test_research_memory_migration_has_core_constraints_and_defaults():
    sql = _migration_sql()

    assert "research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE" in sql
    assert "span_key TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE(research_id, span_version, span_order)" in sql
    assert "chunk_key TEXT NOT NULL UNIQUE" in sql
    assert "UNIQUE(research_id, chunker_version, chunk_order)" in sql
    assert "span_keys TEXT[] NOT NULL DEFAULT '{}'" in sql
    assert "figure_manifest JSONB NOT NULL DEFAULT '[]'" in sql
    assert "metadata JSONB NOT NULL DEFAULT '{}'" in sql
    assert "span_key TEXT NULL REFERENCES research_spans(span_key) ON DELETE SET NULL" in sql
    assert (
        "chunk_key TEXT NULL REFERENCES research_retrieval_chunks(chunk_key) ON DELETE SET NULL"
        in sql
    )
