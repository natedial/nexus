"""SQLite reader for parser state.db."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Iterator

from research_analysis_layer.models.run_models import ParserStateRecord


class StateDbReader:
    """Read parser success rows from SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def _row_to_record(self, row: sqlite3.Row) -> ParserStateRecord:
        return ParserStateRecord(
            file_id=row["file_id"],
            file_name=row["file_name"],
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"]),
            parse_ok=bool(row["parse_ok"]) if row["parse_ok"] is not None else None,
            boilerplate_ok=bool(row["boilerplate_ok"]) if row["boilerplate_ok"] is not None else None,
            metadata_ok=bool(row["metadata_ok"]) if row["metadata_ok"] is not None else None,
            themes_ok=bool(row["themes_ok"]) if row["themes_ok"] is not None else None,
            trades_ok=bool(row["trades_ok"]) if row["trades_ok"] is not None else None,
            storage_ok=bool(row["storage_ok"]) if row["storage_ok"] is not None else None,
            error_message=row["error_message"],
        )

    def get_successful_since(
        self,
        watermark: datetime | None,
        limit: int | None = None,
    ) -> list[ParserStateRecord]:
        """Return completed parser rows newer than the watermark."""
        query = [
            "SELECT * FROM processed_files",
            "WHERE status = 'completed'",
            "AND storage_ok = 1",
        ]
        params: list[object] = []
        if watermark is not None:
            query.append("AND updated_at > ?")
            params.append(watermark.isoformat())
        query.append("ORDER BY updated_at ASC")
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)
        sql = " ".join(query)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_by_file_ids(self, file_ids: list[str]) -> list[ParserStateRecord]:
        """Fetch exact file ids from state.db."""
        if not file_ids:
            return []
        placeholders = ",".join("?" for _ in file_ids)
        sql = (
            "SELECT * FROM processed_files "
            f"WHERE file_id IN ({placeholders}) ORDER BY updated_at ASC"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, file_ids).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_status_counts(self) -> dict[str, int]:
        """Return counts grouped by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM processed_files GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}
