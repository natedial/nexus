"""Local SQLite store for dispatcher-owned run history."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .report_models import DispatchBatch


class DispatchStore:
    """Persist dispatcher runs independently of upstream parser state."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS dispatch_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    input_mode TEXT NOT NULL DEFAULT 'parser',
                    source_type TEXT NULL,
                    analyst_batch_path TEXT NULL,
                    batch_key TEXT NOT NULL,
                    analysis_version TEXT NULL,
                    report_title TEXT NULL,
                    report_scope_json TEXT NOT NULL,
                    source_date_range_json TEXT NULL,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    throughline_count INTEGER NOT NULL DEFAULT 0,
                    callout_count INTEGER NOT NULL DEFAULT 0,
                    pdf_path TEXT NULL,
                    recipients_json TEXT NULL,
                    error_text TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS dispatch_run_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispatch_run_id INTEGER NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NULL,
                    source TEXT NULL,
                    source_date TEXT NULL,
                    document_name TEXT NULL,
                    included INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(dispatch_run_id, research_id, document_hash)
                );

                CREATE TABLE IF NOT EXISTS dispatch_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dispatch_run_id INTEGER NOT NULL,
                    snapshot_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_dispatch_runs_created_at
                    ON dispatch_runs(created_at);
                CREATE INDEX IF NOT EXISTS idx_dispatch_run_items_run_id
                    ON dispatch_run_items(dispatch_run_id);
                CREATE INDEX IF NOT EXISTS idx_dispatch_snapshots_run_id
                    ON dispatch_snapshots(dispatch_run_id);
                """
            )
            self._ensure_columns(
                conn,
                "dispatch_runs",
                {
                    "input_mode": "TEXT NOT NULL DEFAULT 'parser'",
                    "source_type": "TEXT NULL",
                    "analyst_batch_path": "TEXT NULL",
                },
            )

    def create_run(
        self,
        *,
        run_type: str,
        mode: str,
        input_mode: str = "parser",
        source_type: str | None = None,
        analyst_batch_path: str | None = None,
        batch_key: str,
        analysis_version: str | None,
        report_title: str,
        report_scope: dict[str, Any],
        source_date_range: dict[str, Any] | None,
        document_count: int,
    ) -> int:
        now = self._utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO dispatch_runs (
                    run_type,
                    status,
                    mode,
                    input_mode,
                    source_type,
                    analyst_batch_path,
                    batch_key,
                    analysis_version,
                    report_title,
                    report_scope_json,
                    source_date_range_json,
                    document_count,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_type,
                    "running",
                    mode,
                    input_mode,
                    source_type,
                    analyst_batch_path,
                    batch_key,
                    analysis_version,
                    report_title,
                    json.dumps(report_scope, sort_keys=True),
                    json.dumps(source_date_range, sort_keys=True) if source_date_range else None,
                    document_count,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def _ensure_columns(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")
        }
        for column_name, column_spec in columns.items():
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_spec}"
                )

    def record_documents(
        self,
        dispatch_run_id: int,
        documents: list[dict[str, Any]] | DispatchBatch,
    ) -> int:
        rows = self._document_rows(documents)
        if not rows:
            return 0
        now = self._utc_now()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO dispatch_run_items (
                    dispatch_run_id,
                    research_id,
                    document_hash,
                    source,
                    source_date,
                    document_name,
                    included,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """,
                [
                    (
                        dispatch_run_id,
                        row["research_id"],
                        row["document_hash"],
                        row["source"],
                        row["source_date"],
                        row["document_name"],
                        now,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def mark_pdf_generated(
        self,
        dispatch_run_id: int,
        *,
        pdf_path: str,
        throughline_count: int,
        callout_count: int,
    ) -> None:
        self._update_run(
            dispatch_run_id,
            status="generated",
            pdf_path=pdf_path,
            throughline_count=throughline_count,
            callout_count=callout_count,
        )

    def mark_sent(
        self,
        dispatch_run_id: int,
        recipients: list[str],
    ) -> None:
        self._update_run(
            dispatch_run_id,
            status="sent",
            recipients_json=json.dumps(recipients),
        )

    def save_snapshot(
        self,
        dispatch_run_id: int,
        *,
        snapshot_type: str,
        payload: dict[str, Any],
    ) -> int:
        now = self._utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO dispatch_snapshots (
                    dispatch_run_id,
                    snapshot_type,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    dispatch_run_id,
                    snapshot_type,
                    json.dumps(payload, sort_keys=True),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def finalize_run(
        self,
        dispatch_run_id: int,
        *,
        status: str,
        error_text: str | None = None,
    ) -> None:
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dispatch_runs
                SET status = ?,
                    error_text = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    error_text,
                    now,
                    now,
                    dispatch_run_id,
                ),
            )

    def get_run(self, dispatch_run_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatch_runs WHERE id = ?",
                (dispatch_run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_run_items(self, dispatch_run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM dispatch_run_items
                WHERE dispatch_run_id = ?
                ORDER BY research_id ASC
                """,
                (dispatch_run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshots(self, dispatch_run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM dispatch_snapshots
                WHERE dispatch_run_id = ?
                ORDER BY id ASC
                """,
                (dispatch_run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _update_run(self, dispatch_run_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = self._utc_now()
        assignments = ", ".join(f"{column} = ?" for column in fields)
        values = list(fields.values())
        values.append(dispatch_run_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE dispatch_runs SET {assignments} WHERE id = ?",
                values,
            )

    def _document_rows(
        self,
        documents: list[dict[str, Any]] | DispatchBatch,
    ) -> list[dict[str, Any]]:
        if isinstance(documents, DispatchBatch):
            return [
                {
                    "research_id": document.research_id,
                    "document_hash": document.document_hash,
                    "source": document.source,
                    "source_date": document.source_date,
                    "document_name": document.document_name,
                }
                for document in documents.documents
            ]

        rows: list[dict[str, Any]] = []
        for document in documents:
            research_id = document.get("id")
            try:
                research_id = int(research_id)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "research_id": research_id,
                    "document_hash": document.get("document_hash"),
                    "source": document.get("source"),
                    "source_date": document.get("source_date"),
                    "document_name": document.get("document_name"),
                }
            )
        return rows

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
