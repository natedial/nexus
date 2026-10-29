from __future__ import annotations

from datetime import UTC, datetime, time

from research_pipeline_ops.monitor import HealthCondition, evaluate_job

NOW = datetime(2026, 10, 20, 16, 0, tzinfo=UTC)


def job(**overrides):
    value = {
        "job_key": "test.hourly",
        "schedule_type": "interval",
        "schedule_interval_seconds": 3600,
        "schedule_local_time": None,
        "schedule_weekdays": None,
        "schedule_timezone": None,
        "grace_seconds": 300,
        "stall_seconds": 900,
        "enabled_at": datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
    }
    value.update(overrides)
    return value


def run(**overrides):
    value = {
        "run_key": "run:1",
        "status": "succeeded",
        "started_at": datetime(2026, 10, 20, 15, 30, tzinfo=UTC),
        "heartbeat_at": datetime(2026, 10, 20, 15, 35, tzinfo=UTC),
        "completed_at": datetime(2026, 10, 20, 15, 35, tzinfo=UTC),
        "error_text": None,
    }
    value.update(overrides)
    return value


def kinds(conditions) -> list[str]:
    return [condition.kind for condition in conditions]


def test_interval_job_is_healthy_inside_interval_and_grace() -> None:
    assert evaluate_job(job(), run(), now=NOW) == []


def test_interval_job_becomes_overdue() -> None:
    old = run(started_at=datetime(2026, 10, 20, 14, 0, tzinfo=UTC))
    assert kinds(evaluate_job(job(), old, now=NOW)) == ["overdue"]


def test_never_run_job_uses_enabled_at_as_interval_anchor() -> None:
    assert kinds(evaluate_job(job(), None, now=NOW)) == ["overdue"]


def test_running_job_becomes_stalled_from_heartbeat_age() -> None:
    latest = run(
        status="running",
        heartbeat_at=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        completed_at=None,
    )
    assert kinds(evaluate_job(job(), latest, now=NOW)) == ["stalled"]


def test_failed_and_degraded_runs_have_distinct_severity() -> None:
    failed = evaluate_job(job(), run(status="failed", error_text="offline"), now=NOW)
    degraded = evaluate_job(job(), run(status="degraded", error_text="one item"), now=NOW)
    assert [(item.kind, item.severity) for item in failed] == [("failed", "error")]
    assert [(item.kind, item.severity) for item in degraded] == [("degraded", "warning")]


def test_daily_schedule_uses_local_timezone_and_grace() -> None:
    daily = job(
        schedule_type="daily",
        schedule_interval_seconds=None,
        schedule_local_time=time(4, 0),
        schedule_timezone="America/New_York",
        grace_seconds=3600,
    )
    before_today = run(started_at=datetime(2026, 10, 19, 9, 0, tzinfo=UTC))
    assert kinds(evaluate_job(daily, before_today, now=NOW)) == ["overdue"]
    today = run(started_at=datetime(2026, 10, 20, 8, 5, tzinfo=UTC))
    assert evaluate_job(daily, today, now=NOW) == []


def test_daily_schedule_handles_daylight_saving_transition() -> None:
    daily = job(
        schedule_type="daily",
        schedule_interval_seconds=None,
        schedule_local_time=time(4, 0),
        schedule_timezone="America/New_York",
        grace_seconds=1800,
    )
    after_spring_forward = datetime(2026, 3, 8, 13, 0, tzinfo=UTC)
    before_schedule = run(started_at=datetime(2026, 3, 8, 7, 30, tzinfo=UTC))
    after_schedule = run(started_at=datetime(2026, 3, 8, 8, 5, tzinfo=UTC))
    assert kinds(evaluate_job(daily, before_schedule, now=after_spring_forward)) == ["overdue"]
    assert evaluate_job(daily, after_schedule, now=after_spring_forward) == []


def test_weekday_schedule_uses_friday_on_weekend() -> None:
    weekday = job(
        schedule_type="weekdays",
        schedule_interval_seconds=None,
        schedule_local_time=time(6, 25),
        schedule_timezone="America/New_York",
        schedule_weekdays=[1, 2, 3, 4, 5],
        grace_seconds=1800,
    )
    saturday = datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
    friday_run = run(started_at=datetime(2026, 10, 23, 10, 30, tzinfo=UTC))
    assert evaluate_job(weekday, friday_run, now=saturday) == []


def test_incident_key_is_stable_for_same_condition() -> None:
    first = HealthCondition("job", "failed", "error", "one", "same", "run:1")
    second = HealthCondition("job", "failed", "error", "two", "same", "run:2")
    assert first.incident_key == second.incident_key
