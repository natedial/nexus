"""Local SQLite state store for tracking processed files."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterator

import structlog

logger = structlog.get_logger()


class ProcessingStatus(str, Enum):
    """Status of a file in the processing pipeline."""

    PENDING = "pending"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # Some steps succeeded, some failed


@dataclass
class FileState:
    """State of a processed file.

    Note: Synthesis is now performed downstream by research_dispatcher.
    """

    file_id: str
    file_name: str
    status: ProcessingStatus
    created_at: datetime
    updated_at: datetime
    parse_ok: bool | None = None
    boilerplate_ok: bool | None = None
    metadata_ok: bool | None = None
    themes_ok: bool | None = None
    trades_ok: bool | None = None
    storage_ok: bool | None = None
    error_message: str | None = None


class StateStore:
    """SQLite-based state store for tracking processed files."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_files (
                    file_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    parse_ok INTEGER,
                    boilerplate_ok INTEGER,
                    metadata_ok INTEGER,
                    themes_ok INTEGER,
                    trades_ok INTEGER,
                    storage_ok INTEGER,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON processed_files(status)
            """)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def is_processed(self, file_id: str) -> bool:
        """Check if a file has already been successfully processed."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM processed_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            if row is None:
                return False
            return row["status"] in (ProcessingStatus.COMPLETED.value, ProcessingStatus.PARTIAL.value)

    def get_state(self, file_id: str) -> FileState | None:
        """Get the current state of a file."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM processed_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            if row is None:
                return None
            return FileState(
                file_id=row["file_id"],
                file_name=row["file_name"],
                status=ProcessingStatus(row["status"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                parse_ok=bool(row["parse_ok"]) if row["parse_ok"] is not None else None,
                boilerplate_ok=bool(row["boilerplate_ok"]) if row["boilerplate_ok"] is not None else None,
                metadata_ok=bool(row["metadata_ok"]) if row["metadata_ok"] is not None else None,
                themes_ok=bool(row["themes_ok"]) if row["themes_ok"] is not None else None,
                trades_ok=bool(row["trades_ok"]) if row["trades_ok"] is not None else None,
                storage_ok=bool(row["storage_ok"]) if row["storage_ok"] is not None else None,
                error_message=row["error_message"],
            )

    def start_processing(self, file_id: str, file_name: str) -> None:
        """Mark a file as starting processing."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO processed_files (file_id, file_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (file_id, file_name, ProcessingStatus.PENDING.value, now, now),
            )
            conn.commit()
        logger.info("Started processing", file_id=file_id, file_name=file_name)

    def update_step(
        self,
        file_id: str,
        step: str,
        success: bool,
        status: ProcessingStatus | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a processing step."""
        now = datetime.utcnow().isoformat()
        step_col = f"{step}_ok"

        with self._connect() as conn:
            # Build update query
            updates = [f"{step_col} = ?", "updated_at = ?"]
            params: list = [int(success), now]

            if status is not None:
                updates.append("status = ?")
                params.append(status.value)

            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(file_id)

            conn.execute(
                f"UPDATE processed_files SET {', '.join(updates)} WHERE file_id = ?",
                params,
            )
            conn.commit()

        logger.info(
            "Updated step",
            file_id=file_id,
            step=step,
            success=success,
            status=status.value if status else None,
        )

    def mark_completed(self, file_id: str) -> None:
        """Mark a file as fully completed."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_files SET status = ?, updated_at = ? WHERE file_id = ?",
                (ProcessingStatus.COMPLETED.value, now, file_id),
            )
            conn.commit()
        logger.info("Completed processing", file_id=file_id)

    def mark_partial(self, file_id: str, error_message: str | None = None) -> None:
        """Mark a file as partially completed (some steps failed)."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_files SET status = ?, updated_at = ?, error_message = ? WHERE file_id = ?",
                (ProcessingStatus.PARTIAL.value, now, error_message, file_id),
            )
            conn.commit()
        logger.info("Partial completion", file_id=file_id, error=error_message)

    def mark_failed(self, file_id: str, error_message: str) -> None:
        """Mark a file as failed."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE processed_files SET status = ?, updated_at = ?, error_message = ? WHERE file_id = ?",
                (ProcessingStatus.FAILED.value, now, error_message, file_id),
            )
            conn.commit()
        logger.error("Processing failed", file_id=file_id, error=error_message)

    def get_failed_files(self) -> list[FileState]:
        """Get all files that failed processing (for retry)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM processed_files WHERE status = ?",
                (ProcessingStatus.FAILED.value,),
            ).fetchall()
            return [
                FileState(
                    file_id=row["file_id"],
                    file_name=row["file_name"],
                    status=ProcessingStatus(row["status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    error_message=row["error_message"],
                )
                for row in rows
            ]

    def delete_state(self, file_id: str) -> None:
        """Remove a file from the state store."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM processed_files WHERE file_id = ?",
                (file_id,),
            )
            conn.commit()
        logger.info("Deleted state entry", file_id=file_id)
