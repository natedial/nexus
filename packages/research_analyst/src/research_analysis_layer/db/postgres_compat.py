"""SQLite-shaped connection wrapper over psycopg for AnalysisStore."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

_INSERT_OR_IGNORE_CONFLICTS: dict[str, str] = {
    "world_node_evidence": (
        "(node_key, research_id, document_hash, chunk_order, assertion_order)"
    ),
    "world_edge_evidence": (
        "(edge_key, research_id, document_hash, chunk_order, assertion_order)"
    ),
    "world_edge_history": (
        "(edge_key, research_id, document_hash, chunk_order, assertion_order)"
    ),
    "consensus_shift_events": "(event_key)",
}

_INSERT_OR_REPLACE_CONFLICTS: dict[str, str] = {
    "analysis_run_items": "(run_id, file_id)",
    "debate_turns": "(turn_id)",
    "debate_arguments": "(argument_id)",
    "debate_relations": "(relation_id)",
    "debate_scores": "(score_id)",
    "debate_verdicts": "(verdict_id)",
}


class _PostgresRow(dict[str, Any]):
    """Dict row that also supports sqlite3.Row-style key access."""


class _PostgresCursor:
    def __init__(self, cursor: psycopg.Cursor, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self) -> _PostgresRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _PostgresRow(row)

    def fetchall(self) -> list[_PostgresRow]:
        return [_PostgresRow(row) for row in self._cursor.fetchall()]


def _translate_placeholders(sql: str) -> str:
    return sql.replace("?", "%s")


def _translate_insert_or_ignore(sql: str) -> str:
    if "INSERT OR IGNORE" not in sql:
        return sql
    match = re.search(r"INSERT OR IGNORE INTO\s+(\w+)", sql, flags=re.IGNORECASE)
    if not match:
        return sql.replace("INSERT OR IGNORE", "INSERT")
    table = match.group(1)
    conflict = _INSERT_OR_IGNORE_CONFLICTS.get(table)
    translated = sql.replace("INSERT OR IGNORE", "INSERT", 1)
    if conflict and "ON CONFLICT" not in translated.upper():
        translated = translated.rstrip().rstrip(";") + f" ON CONFLICT {conflict} DO NOTHING"
    return translated


def _translate_insert_or_replace(sql: str) -> str:
    if "INSERT OR REPLACE" not in sql:
        return sql
    match = re.search(
        r"INSERT OR REPLACE INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return sql.replace("INSERT OR REPLACE", "INSERT", 1)
    table, columns_raw, _values_raw = match.groups()
    conflict = _INSERT_OR_REPLACE_CONFLICTS.get(table)
    columns = [item.strip() for item in columns_raw.split(",")]
    if not conflict:
        return sql.replace("INSERT OR REPLACE", "INSERT", 1)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in columns if column != "id"
    )
    translated = sql.replace("INSERT OR REPLACE", "INSERT", 1)
    translated = translated.rstrip().rstrip(";")
    translated += f" ON CONFLICT {conflict} DO UPDATE SET {updates}"
    return translated


def adapt_sql(sql: str) -> str:
    translated = _translate_insert_or_replace(sql)
    translated = _translate_insert_or_ignore(translated)
    return _translate_placeholders(translated)


class PostgresCompatConnection:
    """Expose a sqlite3-like API on top of psycopg."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> _PostgresCursor:
        adapted = adapt_sql(sql)
        wants_id = adapted.lstrip().upper().startswith("INSERT") and "RETURNING" not in adapted.upper()
        if wants_id:
            adapted = adapted.rstrip().rstrip(";") + " RETURNING id"
        cursor = self._conn.execute(adapted, params)
        lastrowid = None
        if wants_id:
            row = cursor.fetchone()
            if row is not None:
                lastrowid = int(row["id"])
        return _PostgresCursor(cursor, lastrowid)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            chunk = statement.strip()
            if chunk:
                self._conn.execute(chunk)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


@contextmanager
def postgres_connection(database_url: str) -> Iterator[PostgresCompatConnection]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        wrapper = PostgresCompatConnection(conn)
        try:
            yield wrapper
            conn.commit()
        finally:
            wrapper.close()
