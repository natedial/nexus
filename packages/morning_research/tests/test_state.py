"""Unit tests for digest state helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from morning_research.models import ProcessedDocumentRecord, RunState
from morning_research.state import load_state, processing_window, save_state


def test_atomic_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = RunState(
        last_successful_run="2026-07-20T12:00:00Z",
        processed_documents={
            "abc": ProcessedDocumentRecord(
                file_id="abc",
                file_name="note.pdf",
                content_hash="sha256:1",
                publication_date=None,
                drive_modified_timestamp="2026-07-20T11:00:00Z",
                date_first_processed="2026-07-20T12:00:00Z",
                date_last_processed="2026-07-20T12:00:00Z",
            )
        },
        last_created_notion_page_id="page-1",
    )
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.last_successful_run == "2026-07-20T12:00:00Z"
    assert loaded.last_created_notion_page_id == "page-1"
    assert loaded.processed_documents["abc"].content_hash == "sha256:1"


def test_processing_window_fallback() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    start, used_fallback = processing_window(RunState(), now=now)
    assert used_fallback is True
    assert (now - start).total_seconds() == 24 * 3600


def test_processing_window_from_state() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    state = RunState(last_successful_run="2026-07-23T10:00:00Z")
    start, used_fallback = processing_window(state, now=now)
    assert used_fallback is False
    assert start == datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
