from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from research_pipeline_ops.client import PipelineOpsClient
from research_pipeline_ops.monitor import PipelineOpsMonitor

DATABASE_URL = os.getenv("NEXUS_OPS_TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="set NEXUS_OPS_TEST_DATABASE_URL to a disposable migrated database",
    ),
]


def test_run_event_and_monitor_round_trip(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:12]
    job_key = f"test.integration.{suffix}"
    document_key = f"file:{suffix}"
    run_key = None
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_ops.jobs (
                job_key, repo_name, run_type, enabled, enabled_at,
                schedule_type, schedule_interval_seconds, grace_seconds,
                stall_seconds, retry_policy, playbook_key
            ) VALUES (%s, 'tests', 'integration', true, now(),
                'interval', 3600, 60, 300, 'never', 'tests.integration')
            """,
            (job_key,),
        )
    try:
        client = PipelineOpsClient(
            database_url=DATABASE_URL,
            spool_db_path=tmp_path / "spool.db",
            emitted_by="integration_tests",
            mode="required",
        )
        run_key = client.start_run(job_key=job_key, trigger_source="pytest")
        assert run_key is not None
        client.emit_stage_event(
            repo_name="tests",
            stage_name="tests.work",
            status="succeeded",
            run_key=run_key,
            document_key=document_key,
            file_id=suffix,
            payload={"count": 1},
            document_fields={
                "document_name": "Synthetic integration document",
                "source": "pytest",
                "source_date": "2026-10-20",
            },
        )
        client.finish_run(run_key, status="succeeded", stats={"count": 1}, exit_code=0)

        assert PipelineOpsMonitor(DATABASE_URL).check() == []
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT status, exit_code FROM pipeline_ops.runs WHERE run_key = %s",
                (run_key,),
            ).fetchone()
            document = connection.execute(
                """
                SELECT document_name, source, source_date
                FROM pipeline_ops.documents
                WHERE document_key = %s
                """,
                (document_key,),
            ).fetchone()
        assert row == ("succeeded", 0)
        assert document == (
            "Synthetic integration document",
            "pytest",
            datetime(2026, 10, 20, tzinfo=UTC).date(),
        )
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM pipeline_ops.incidents WHERE job_key = %s", (job_key,))
            if run_key is not None:
                connection.execute(
                    "DELETE FROM pipeline_ops.run_stage_state WHERE run_key = %s",
                    (run_key,),
                )
                connection.execute(
                    "DELETE FROM pipeline_ops.stage_events WHERE run_key = %s", (run_key,)
                )
                connection.execute(
                    "DELETE FROM pipeline_ops.document_stage_state WHERE document_key = %s",
                    (document_key,),
                )
                connection.execute(
                    "DELETE FROM pipeline_ops.documents WHERE document_key = %s",
                    (document_key,),
                )
                connection.execute("DELETE FROM pipeline_ops.runs WHERE run_key = %s", (run_key,))
            connection.execute("DELETE FROM pipeline_ops.jobs WHERE job_key = %s", (job_key,))


def test_incident_deduplication_claim_and_automatic_recovery(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:12]
    job_key = f"test.incident.{suffix}"
    monitor = PipelineOpsMonitor(DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_ops.jobs (
                job_key, repo_name, run_type, enabled, enabled_at,
                schedule_type, schedule_interval_seconds, grace_seconds,
                stall_seconds, retry_policy, playbook_key
            ) VALUES (%s, 'tests', 'incident', true, %s,
                'interval', 60, 0, 300, 'never', 'tests.incident')
            """,
            (job_key, datetime.now(UTC) - timedelta(minutes=10)),
        )
    run_key = None
    try:
        first = monitor.check()
        incident = next(item for item in first if item["job_key"] == job_key)
        assert incident["kind"] == "overdue"
        assert incident["occurrence_count"] == 1

        second = monitor.check()
        repeated = next(item for item in second if item["job_key"] == job_key)
        assert repeated["incident_key"] == incident["incident_key"]
        assert repeated["occurrence_count"] == 1

        claimed = monitor.claim(actor="first-agent", limit=1)
        assert [item["incident_key"] for item in claimed] == [incident["incident_key"]]
        assert monitor.claim(actor="second-agent", limit=1) == []

        client = PipelineOpsClient(
            database_url=DATABASE_URL,
            spool_db_path=tmp_path / "incident-spool.db",
            emitted_by="integration_tests",
            mode="required",
        )
        run_key = client.start_run(job_key=job_key, trigger_source="pytest")
        assert run_key is not None
        client.finish_run(run_key, status="succeeded", exit_code=0)
        assert not any(item["job_key"] == job_key for item in monitor.check())

        resolved = monitor.list_incidents(status="resolved")
        recovered = next(
            item for item in resolved if item["incident_key"] == incident["incident_key"]
        )
        assert recovered["resolution_summary"] == "superseded by current healthy state"
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM pipeline_ops.incidents WHERE job_key = %s", (job_key,))
            if run_key is not None:
                connection.execute("DELETE FROM pipeline_ops.runs WHERE run_key = %s", (run_key,))
            connection.execute("DELETE FROM pipeline_ops.jobs WHERE job_key = %s", (job_key,))


def test_spooled_operation_replays_exactly_once(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:12]
    job_key = f"test.spool.{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_ops.jobs (
                job_key, repo_name, run_type, enabled,
                schedule_type, schedule_interval_seconds, grace_seconds,
                stall_seconds, retry_policy, playbook_key
            ) VALUES (%s, 'tests', 'spool', false,
                'interval', 3600, 60, 300, 'never', 'tests.spool')
            """,
            (job_key,),
        )
    client = PipelineOpsClient(
        database_url=None,
        spool_db_path=tmp_path / "replay.db",
        emitted_by="integration_tests",
        mode="best_effort",
    )
    run_key = client.start_run(job_key=job_key, trigger_source="pytest")
    assert run_key is not None
    assert client.spool_depth() == 1
    try:
        client.database_url = DATABASE_URL
        client.finish_run(run_key, status="succeeded", exit_code=0)
        assert client.spool_depth() == 0
        assert client.flush() == 0
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute(
                "SELECT count(*), max(status) FROM pipeline_ops.runs WHERE run_key = %s",
                (run_key,),
            ).fetchone()
        assert row == (1, "succeeded")
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM pipeline_ops.runs WHERE run_key = %s", (run_key,))
            connection.execute("DELETE FROM pipeline_ops.jobs WHERE job_key = %s", (job_key,))


def test_retry_dry_run_uses_only_catalogued_launchd_label(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:12]
    job_key = f"test.retry.{suffix}"
    label = f"com.nexus.test-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_ops.jobs (
                job_key, repo_name, run_type, enabled, enabled_at,
                schedule_type, retry_policy, launchd_label,
                grace_seconds, stall_seconds, playbook_key
            ) VALUES (%s, 'tests', 'retry', true, now(),
                'external', 'kickstart_once', %s, 60, 300, 'tests.retry')
            """,
            (job_key, label),
        )
    client = PipelineOpsClient(
        database_url=DATABASE_URL,
        spool_db_path=tmp_path / "retry.db",
        emitted_by="integration_tests",
        mode="required",
    )
    run_key = client.start_run(job_key=job_key, trigger_source="pytest")
    assert run_key is not None
    client.finish_run(run_key, status="failed", error_text="synthetic", exit_code=1)
    monitor = PipelineOpsMonitor(DATABASE_URL)
    try:
        incident = next(item for item in monitor.check() if item["job_key"] == job_key)
        result = monitor.retry(
            incident_key=incident["incident_key"],
            actor="integration-test",
            dry_run=True,
        )
        assert result["status"] == "dry_run"
        assert result["command"][-1].endswith(f"/{label}")
        with psycopg.connect(DATABASE_URL) as connection:
            attempts = connection.execute(
                "SELECT count(*) FROM pipeline_ops.remediation_attempts WHERE job_key = %s",
                (job_key,),
            ).fetchone()
        assert attempts == (0,)
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM pipeline_ops.incidents WHERE job_key = %s", (job_key,))
            connection.execute("DELETE FROM pipeline_ops.runs WHERE run_key = %s", (run_key,))
            connection.execute("DELETE FROM pipeline_ops.jobs WHERE job_key = %s", (job_key,))


def test_skipped_overlap_does_not_hide_stalled_active_run(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    suffix = uuid.uuid4().hex[:12]
    job_key = f"test.overlap.{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_ops.jobs (
                job_key, repo_name, run_type, enabled,
                schedule_type, retry_policy, grace_seconds,
                stall_seconds, playbook_key
            ) VALUES (%s, 'tests', 'overlap', true,
                'external', 'never', 60, 300, 'tests.overlap')
            """,
            (job_key,),
        )
    client = PipelineOpsClient(
        database_url=DATABASE_URL,
        spool_db_path=tmp_path / "overlap.db",
        emitted_by="integration_tests",
        mode="required",
    )
    active_run = client.start_run(
        job_key=job_key,
        trigger_source="pytest",
        started_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    skipped_run = client.start_run(job_key=job_key, trigger_source="pytest")
    assert active_run is not None and skipped_run is not None
    client.finish_run(skipped_run, status="skipped", exit_code=0)
    try:
        incidents = PipelineOpsMonitor(DATABASE_URL).check()
        stalled = next(item for item in incidents if item["job_key"] == job_key)
        assert stalled["kind"] == "stalled"
        assert stalled["latest_run_key"] == active_run
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM pipeline_ops.incidents WHERE job_key = %s", (job_key,))
            connection.execute(
                "DELETE FROM pipeline_ops.runs WHERE run_key IN (%s, %s)",
                (active_run, skipped_run),
            )
            connection.execute("DELETE FROM pipeline_ops.jobs WHERE job_key = %s", (job_key,))
