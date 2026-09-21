"""Local SQLite state store for tracking processed files."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

import structlog

logger = structlog.get_logger()

_TRANSIENT_ERROR_MARKERS = (
    "scheduler is not running",
    "ratelimiterror",
    "rate limit",
    "too many requests",
    "429",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "connection error",
    "connection reset",
)


class ProcessingStatus(StrEnum):
    """Status of a file in the processing pipeline."""

    PENDING = "pending"
    PARSING = "parsing"
    EXTRACTING = "extracting"  # legacy rows from the old extraction worker
    STORING = "storing"
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relay_intake (
                    relay_key TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    storage_ok INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
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
        """Check if a file is terminal and should be skipped by polling.

        COMPLETED is always terminal. PARTIAL/FAILED can be retried when
        their error message indicates a transient failure.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, error_message, storage_ok FROM processed_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            if row is None:
                return False
            status = row["status"]
            if status == ProcessingStatus.COMPLETED.value or row["storage_ok"] == 1:
                return True
            if status in (ProcessingStatus.PARTIAL.value, ProcessingStatus.FAILED.value):
                return not self._is_transient_error(row["error_message"])
            return False

    @staticmethod
    def _is_transient_error(error_message: str | None) -> bool:
        if not error_message:
            return False
        message = error_message.lower()
        return any(marker in message for marker in _TRANSIENT_ERROR_MARKERS)

    @staticmethod
    def _clear_step_error_fragment(
        error_message: str | None,
        step: str,
    ) -> str | None:
        """Remove stale error text for a step that has since succeeded.

        The current schema has a single error_message column, so retry summaries
        are commonly formatted as semicolon-separated step fragments.
        """
        if not error_message:
            return None

        step_marker = f"{step.lower()}:"
        failed_marker = f"{step.replace('_', ' ').title()} failed:"
        kept_parts = []
        for part in error_message.split(";"):
            cleaned = part.strip()
            lowered = cleaned.lower()
            if lowered.startswith(step_marker) or lowered.startswith(failed_marker.lower()):
                continue
            kept_parts.append(cleaned)

        if len(kept_parts) == len(error_message.split(";")):
            return error_message
        return "; ".join(part for part in kept_parts if part) or None

    @staticmethod
    def _row_to_file_state(row: sqlite3.Row) -> FileState:
        return FileState(
            file_id=row["file_id"],
            file_name=row["file_name"],
            status=ProcessingStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            parse_ok=bool(row["parse_ok"]) if row["parse_ok"] is not None else None,
            boilerplate_ok=(
                bool(row["boilerplate_ok"]) if row["boilerplate_ok"] is not None else None
            ),
            metadata_ok=bool(row["metadata_ok"]) if row["metadata_ok"] is not None else None,
            themes_ok=bool(row["themes_ok"]) if row["themes_ok"] is not None else None,
            trades_ok=bool(row["trades_ok"]) if row["trades_ok"] is not None else None,
            storage_ok=bool(row["storage_ok"]) if row["storage_ok"] is not None else None,
            error_message=row["error_message"],
        )

    def get_state(self, file_id: str) -> FileState | None:
        """Get the current state of a file."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM processed_files WHERE file_id = ?",
                (file_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_file_state(row)

    def get_stale_in_progress(self, max_age_minutes: int) -> list[FileState]:
        """Return files stuck in non-terminal states beyond the age threshold."""
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cutoff_iso = cutoff.isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM processed_files
                WHERE status IN (?, ?, ?, ?)
                  AND COALESCE(storage_ok, 0) != 1
                  AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (
                    ProcessingStatus.PENDING.value,
                    ProcessingStatus.PARSING.value,
                    ProcessingStatus.EXTRACTING.value,
                    ProcessingStatus.STORING.value,
                    cutoff_iso,
                ),
            ).fetchall()

        stale = [self._row_to_file_state(row) for row in rows]
        if stale:
            logger.warning(
                "Found stale in-progress files",
                count=len(stale),
                max_age_minutes=max_age_minutes,
            )
        return stale

    def get_retryable_partials(self, max_age_minutes: int) -> list[FileState]:
        """Return partial rows old enough to retry on the next poll cycle."""
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cutoff_iso = cutoff.isoformat()

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM processed_files
                WHERE status = ?
                  AND COALESCE(storage_ok, 0) != 1
                  AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (ProcessingStatus.PARTIAL.value, cutoff_iso),
            ).fetchall()

        retryable = [self._row_to_file_state(row) for row in rows]
        if retryable:
            logger.info(
                "Found retryable partial files",
                count=len(retryable),
                max_age_minutes=max_age_minutes,
            )
        return retryable

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
            elif success:
                row = conn.execute(
                    "SELECT error_message FROM processed_files WHERE file_id = ?",
                    (file_id,),
                ).fetchone()
                cleaned_error = self._clear_step_error_fragment(
                    row["error_message"] if row else None,
                    step,
                )
                if row is not None and cleaned_error != row["error_message"]:
                    updates.append("error_message = ?")
                    params.append(cleaned_error)

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
                """
                UPDATE processed_files
                SET status = ?,
                    updated_at = ?,
                    parse_ok = 1,
                    boilerplate_ok = 1,
                    storage_ok = 1,
                    error_message = NULL
                WHERE file_id = ?
                """,
                (ProcessingStatus.COMPLETED.value, now, file_id),
            )
            conn.commit()
        logger.info("Completed processing", file_id=file_id)

    def mark_partial(self, file_id: str, error_message: str | None = None) -> None:
        """Mark a file as partially completed (some steps failed)."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_files
                SET status = ?, updated_at = ?, error_message = ?
                WHERE file_id = ?
                  AND status != ?
                  AND COALESCE(storage_ok, 0) != 1
                """,
                (
                    ProcessingStatus.PARTIAL.value,
                    now,
                    error_message,
                    file_id,
                    ProcessingStatus.COMPLETED.value,
                ),
            )
            conn.commit()
        logger.info("Partial completion", file_id=file_id, error=error_message)

    def mark_failed(self, file_id: str, error_message: str) -> None:
        """Mark a file as failed."""
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE processed_files
                SET status = ?, updated_at = ?, error_message = ?
                WHERE file_id = ?
                  AND status != ?
                  AND COALESCE(storage_ok, 0) != 1
                """,
                (
                    ProcessingStatus.FAILED.value,
                    now,
                    error_message,
                    file_id,
                    ProcessingStatus.COMPLETED.value,
                ),
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
            return [self._row_to_file_state(row) for row in rows]

    def delete_state(self, file_id: str) -> None:
        """Remove a file from the state store."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM processed_files WHERE file_id = ?",
                (file_id,),
            )
            conn.commit()
        logger.info("Deleted state entry", file_id=file_id)

    def is_relay_intake_complete(self, relay_key: str, content_hash: str) -> bool:
        """Return True when this relay key/hash was already stored successfully."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content_hash, storage_ok
                FROM relay_intake
                WHERE relay_key = ?
                """,
                (relay_key,),
            ).fetchone()
        if row is None:
            return False
        return row["content_hash"] == content_hash and row["storage_ok"] == 1

    def record_relay_intake(
        self,
        relay_key: str,
        *,
        content_hash: str,
        document_id: str,
        file_id: str,
        storage_ok: bool,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO relay_intake (
                    relay_key, content_hash, document_id, file_id,
                    storage_ok, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relay_key) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    document_id = excluded.document_id,
                    file_id = excluded.file_id,
                    storage_ok = excluded.storage_ok,
                    updated_at = excluded.updated_at
                """,
                (
                    relay_key,
                    content_hash,
                    document_id,
                    file_id,
                    int(storage_ok),
                    now,
                    now,
                ),
            )
            conn.commit()
