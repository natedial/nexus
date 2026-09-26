"""Unit tests for PostgreSQL sqlite-compat SQL adaptation."""

from unittest.mock import MagicMock

from research_analysis_layer.db.postgres_compat import (
    PostgresCompatConnection,
    returning_column_for_insert,
)


def test_returning_column_skips_analysis_documents():
    sql = """
        INSERT INTO analysis_documents (research_id, document_hash, ingested_at)
        VALUES (%s, %s, %s)
        ON CONFLICT(research_id) DO UPDATE SET document_hash = excluded.document_hash
    """
    assert returning_column_for_insert(sql) is None


def test_returning_column_defaults_to_id_for_serial_tables():
    sql = """
        INSERT INTO analysis_runs (
            run_type, status, trigger_source, analysis_version,
            chunker_version, assertion_extractor_version, resolver_version,
            started_at, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    assert returning_column_for_insert(sql) == "id"


def test_execute_does_not_append_returning_id_for_analysis_documents():
    conn = MagicMock()
    executed_sql: list[str] = []

    def capture_execute(sql: str, params: tuple[object, ...] = ()) -> MagicMock:
        executed_sql.append(sql)
        return MagicMock(fetchone=MagicMock(return_value=None))

    conn.execute.side_effect = capture_execute
    wrapper = PostgresCompatConnection(conn)
    wrapper.execute(
        """
        INSERT INTO analysis_documents (
            research_id, document_hash, ingested_at
        ) VALUES (?, ?, ?)
        ON CONFLICT(research_id) DO UPDATE SET ingested_at = excluded.ingested_at
        """,
        (42, "hash", "2026-01-01T00:00:00+00:00"),
    )
    assert len(executed_sql) == 1
    assert "RETURNING" not in executed_sql[0].upper()


def test_execute_appends_returning_id_for_analysis_runs():
    conn = MagicMock()
    executed_sql: list[str] = []

    def capture_execute(sql: str, params: tuple[object, ...] = ()) -> MagicMock:
        executed_sql.append(sql)
        return MagicMock(fetchone=MagicMock(return_value={"id": 7}))

    conn.execute.side_effect = capture_execute
    wrapper = PostgresCompatConnection(conn)
    cursor = wrapper.execute(
        "INSERT INTO analysis_runs (run_type, status) VALUES (?, ?)",
        ("batch", "running"),
    )
    assert executed_sql[0].rstrip().endswith("RETURNING id")
    assert cursor.lastrowid == 7
