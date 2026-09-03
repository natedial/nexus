from datetime import datetime, timedelta

from src.storage.state import ProcessingStatus, StateStore


def test_is_processed_retries_transient_failed_status(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-transient-failed"
    store.start_processing(file_id, "doc.pdf")
    store.mark_failed(file_id, "Download failed: Scheduler is not running")

    assert not store.is_processed(file_id)


def test_is_processed_retries_transient_partial_status(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-transient-partial"
    store.start_processing(file_id, "doc.pdf")
    store.mark_partial(file_id, "metadata failed: RateLimitError")

    assert not store.is_processed(file_id)


def test_is_processed_keeps_non_transient_failed_terminal(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-terminal-failed"
    store.start_processing(file_id, "doc.pdf")
    store.mark_failed(file_id, "Storage failed: duplicate key value")

    assert store.is_processed(file_id)


def test_is_processed_keeps_completed_terminal(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-completed"
    store.start_processing(file_id, "doc.pdf")
    store.mark_completed(file_id)

    assert store.is_processed(file_id)


def test_mark_completed_clears_stale_error_message(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-completed-with-old-error"
    store.start_processing(file_id, "doc.pdf")
    store.update_step(file_id, "themes", False, error_message="Themes failed: old model")
    store.mark_completed(file_id)

    state = store.get_state(file_id)

    assert state is not None
    assert state.status == ProcessingStatus.COMPLETED
    assert state.error_message is None
    assert state.parse_ok is True
    assert state.boilerplate_ok is True
    assert state.storage_ok is True


def test_successful_step_update_clears_only_matching_stale_error_fragment(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-step-error-cleanup"
    store.start_processing(file_id, "doc.pdf")
    store.mark_partial(
        file_id,
        "themes: Themes failed: old model; trades: Trades failed: old model",
    )

    store.update_step(file_id, "themes", True)

    state = store.get_state(file_id)

    assert state is not None
    assert state.themes_ok is True
    assert state.error_message == "trades: Trades failed: old model"


def test_terminal_completed_state_is_not_downgraded_by_late_failure(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-completed-terminal"
    store.start_processing(file_id, "doc.pdf")
    store.mark_completed(file_id)

    store.mark_failed(file_id, "late failure")
    store.mark_partial(file_id, "late partial")

    state = store.get_state(file_id)

    assert state is not None
    assert state.status == ProcessingStatus.COMPLETED
    assert state.error_message is None


def test_storage_success_state_is_not_downgraded_by_late_failure(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-storage-terminal"
    store.start_processing(file_id, "doc.pdf")
    store.update_step(file_id, "storage", True)

    store.mark_failed(file_id, "late failure")

    state = store.get_state(file_id)

    assert state is not None
    assert state.status == ProcessingStatus.PENDING
    assert state.storage_ok is True
    assert state.error_message is None
    assert store.is_processed(file_id)


def test_storage_success_state_is_excluded_from_stale_retry(tmp_path):
    store = StateStore(tmp_path / "state.db")
    file_id = "file-storage-stale-terminal"
    store.start_processing(file_id, "doc.pdf")
    store.update_step(file_id, "storage", True)

    stale_timestamp = (datetime.utcnow() - timedelta(minutes=120)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE processed_files SET status = ?, updated_at = ? WHERE file_id = ?",
            (ProcessingStatus.EXTRACTING.value, stale_timestamp, file_id),
        )
        conn.commit()

    assert store.get_stale_in_progress(max_age_minutes=30) == []


def test_get_stale_in_progress_returns_old_non_terminal_rows(tmp_path):
    store = StateStore(tmp_path / "state.db")
    stale_file_id = "file-stale"
    fresh_file_id = "file-fresh"

    store.start_processing(stale_file_id, "stale.pdf")
    store.start_processing(fresh_file_id, "fresh.pdf")

    stale_timestamp = (datetime.utcnow() - timedelta(minutes=120)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE processed_files SET status = ?, updated_at = ? WHERE file_id = ?",
            (ProcessingStatus.PARSING.value, stale_timestamp, stale_file_id),
        )
        conn.execute(
            "UPDATE processed_files SET status = ? WHERE file_id = ?",
            (ProcessingStatus.EXTRACTING.value, fresh_file_id),
        )
        conn.commit()

    stale = store.get_stale_in_progress(max_age_minutes=30)
    stale_ids = {row.file_id for row in stale}

    assert stale_file_id in stale_ids
    assert fresh_file_id not in stale_ids
