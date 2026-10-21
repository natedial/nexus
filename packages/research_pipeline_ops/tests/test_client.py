from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from research_pipeline_ops.client import (
    PipelineOpsClient,
    PipelineOpsConfigurationError,
    make_document_key,
    sanitize_text,
)


def build_client(tmp_path: Path, **overrides) -> PipelineOpsClient:
    values = {
        "database_url": None,
        "spool_db_path": tmp_path / "ops.db",
        "emitted_by": "tests",
        "mode": "best_effort",
    }
    values.update(overrides)
    return PipelineOpsClient(**values)


def test_make_document_key_prefers_file_identity() -> None:
    assert make_document_key(file_id="abc", research_id=4, document_hash="hash") == "file:abc"
    assert make_document_key(research_id=4, document_hash="hash") == "doc:4:hash"
    assert make_document_key(research_id=4) == "research:4"
    assert make_document_key(document_hash="hash") == "hash:hash"


def test_make_document_key_requires_identity() -> None:
    with pytest.raises(ValueError, match="required"):
        make_document_key()


def test_sanitize_text_redacts_common_secret_shapes() -> None:
    value = "postgresql://nexus:hunter2@localhost/db token=abc Bearer xyz\x00"
    clean = sanitize_text(value, max_chars=500)
    assert "hunter2" not in clean
    assert "abc" not in clean
    assert "xyz" not in clean
    assert "\x00" not in clean
    assert clean == "postgresql://nexus:[redacted]@localhost/db token=[redacted] Bearer [redacted]"


def test_required_mode_needs_database_url(tmp_path: Path) -> None:
    with pytest.raises(PipelineOpsConfigurationError, match="required"):
        build_client(tmp_path, mode="required")


def test_best_effort_spools_when_database_is_unconfigured(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    run_key = client.start_run(job_key="gleaner.notion", trigger_source="test")
    assert run_key is not None
    assert client.spool_depth() == 1
    with sqlite3.connect(tmp_path / "ops.db") as connection:
        row = connection.execute(
            "SELECT op_type, attempts, last_error FROM spool_operations"
        ).fetchone()
    assert row == ("start_run", 0, "database URL is not configured")


def test_flush_replays_in_order_and_deletes_only_successes(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    first = client.start_run(job_key="gleaner.notion", trigger_source="test")
    client.heartbeat(first, stats={"seen": 1})
    assert client.spool_depth() == 2

    seen: list[str] = []
    client.database_url = "postgresql://unused"
    client._apply_envelope = lambda envelope: seen.append(envelope["op_type"])  # type: ignore[method-assign]
    assert client.flush() == 2
    assert seen == ["start_run", "heartbeat"]
    assert client.spool_depth() == 0


def test_flush_retains_failed_operation_and_preserves_order(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    run_key = client.start_run(job_key="gleaner.notion", trigger_source="test")
    client.heartbeat(run_key)
    client.database_url = "postgresql://unused"

    def fail(_envelope):
        raise RuntimeError("offline")

    client._apply_envelope = fail  # type: ignore[method-assign]
    assert client.flush() == 0
    assert client.spool_depth() == 2
    with sqlite3.connect(tmp_path / "ops.db") as connection:
        attempts = connection.execute(
            "SELECT attempts FROM spool_operations ORDER BY id"
        ).fetchall()
    assert attempts == [(1,), (0,)]


def test_new_operations_join_existing_spool_before_replay(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    run_key = client.start_run(job_key="gleaner.notion", trigger_source="test")
    assert run_key is not None

    seen: list[str] = []
    client.database_url = "postgresql://unused"
    client._apply_envelope = lambda envelope: seen.append(envelope["op_type"])  # type: ignore[method-assign]
    client.finish_run(run_key, status="succeeded")

    assert seen == ["start_run", "finish_run"]
    assert client.spool_depth() == 0


def test_payload_rejects_non_json_domain_objects(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    with pytest.raises(TypeError, match="unsupported"):
        client.start_run(job_key="gleaner.notion", stats={"capture": object()})


def test_stage_event_rejects_unknown_document_fields(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    with pytest.raises(ValueError, match="unsupported document fields"):
        client.emit_stage_event(
            repo_name="research_parser",
            stage_name="parser.complete",
            status="succeeded",
            document_key="file:one",
            document_fields={"full_text": "must not enter ops"},
        )


class RecordingClient(PipelineOpsClient):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(
            database_url=None,
            spool_db_path=tmp_path / "unused.db",
            emitted_by="tests",
            mode="best_effort",
        )
        self.operations: list[tuple[str, dict]] = []

    def _submit(self, op_type: str, payload):
        self.operations.append((op_type, dict(payload)))


def test_update_run_maps_legacy_completed_status(tmp_path: Path) -> None:
    client = RecordingClient(tmp_path)
    client.update_run("run:1", status="completed", stats={"count": 2}, completed=True)
    assert client.operations[0][0] == "finish_run"
    assert client.operations[0][1]["status"] == "succeeded"


def test_track_stage_records_failure_and_reraises(tmp_path: Path) -> None:
    client = RecordingClient(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        with client.track_stage(repo_name="repo", stage_name="repo.stage", run_key="run:1"):
            raise RuntimeError("boom")
    statuses = [
        payload["status"] for operation, payload in client.operations if operation == "stage_event"
    ]
    assert statuses == ["started", "failed"]
    assert client.operations[-1][1]["error_type"] == "RuntimeError"
