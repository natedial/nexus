"""Load, mutate, and atomically persist the morning-research state file.

The state file tracks the last successful run timestamp, previously
processed documents (keyed by Drive file id), and the most recently created
Notion page id. It is intentionally a plain JSON file (not a database) so it
can be inspected and hand-edited if needed, matching the legacy local_codex
automation's format.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog

from morning_research.models import ProcessedDocumentRecord, RunState

logger = structlog.get_logger()

FALLBACK_WINDOW = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_state(path: Path) -> RunState:
    """Load state from `path`, returning an empty RunState if absent or invalid."""
    if not path.exists():
        logger.info("No existing state file found; starting fresh", path=str(path))
        return RunState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read state file; starting fresh", path=str(path), error=str(exc))
        return RunState()

    return RunState.from_dict(raw)


def save_state(path: Path, state: RunState) -> None:
    """Atomically persist `state` to `path` via temp-file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), indent=2, sort_keys=False) + "\n"

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with _suppress_os_error():
            os.unlink(tmp_path)
        raise
    logger.info("Saved state", path=str(path))


class _suppress_os_error:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


def processing_window(state: RunState, now: datetime | None = None) -> tuple[datetime, bool]:
    """Return (window_start, used_fallback) for this run.

    Uses `state.last_successful_run` if present and parseable; otherwise falls
    back to a 24-hour lookback window.
    """
    now = now or _utcnow()
    if state.last_successful_run:
        try:
            since = datetime.fromisoformat(state.last_successful_run.replace("Z", "+00:00"))
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            return since, False
        except ValueError:
            logger.warning(
                "Could not parse last_successful_run; falling back to 24h window",
                value=state.last_successful_run,
            )
    return now - FALLBACK_WINDOW, True


def is_duplicate_content(state: RunState, content_hash: str) -> bool:
    """True if `content_hash` matches any previously processed document."""
    return content_hash in state.content_hashes()


def already_processed(state: RunState, file_id: str, content_hash: str) -> bool:
    """True if this exact file_id + content_hash pair was already processed."""
    record = state.processed_documents.get(file_id)
    return record is not None and record.content_hash == content_hash


def mark_documents_processed(
    state: RunState,
    file_ids_to_metadata: dict[str, dict[str, str | None]],
    now: datetime | None = None,
) -> RunState:
    """Merge newly analyzed documents into `state.processed_documents`.

    `file_ids_to_metadata` maps file_id -> {file_name, content_hash,
    publication_date, drive_modified_timestamp}. Should only be called by the
    orchestrator after a run has fully succeeded (Codex ran, QC passed,
    Notion page published).
    """
    now_iso = (now or _utcnow()).isoformat()
    for file_id, meta in file_ids_to_metadata.items():
        existing = state.processed_documents.get(file_id)
        first_processed = existing.date_first_processed if existing else now_iso
        state.processed_documents[file_id] = ProcessedDocumentRecord(
            file_id=file_id,
            file_name=meta.get("file_name") or "",
            content_hash=meta.get("content_hash") or "",
            publication_date=meta.get("publication_date"),
            drive_modified_timestamp=meta.get("drive_modified_timestamp") or "",
            date_first_processed=first_processed,
            date_last_processed=now_iso,
        )
    return state


def mark_run_successful(
    state: RunState,
    *,
    notion_page_id: str | None = None,
    now: datetime | None = None,
) -> RunState:
    """Update last_successful_run (and optionally the created page id)."""
    state.last_successful_run = (now or _utcnow()).isoformat()
    if notion_page_id:
        state.last_created_notion_page_id = notion_page_id
    return state
