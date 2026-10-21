"""Job-health evaluation, incident lifecycle, and allowlisted remediation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from research_pipeline_ops.client import sanitize_text, utc_now

_LAUNCHD_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
_INCIDENT_STATUSES = frozenset({"open", "claimed", "resolved", "suppressed"})


@dataclass(frozen=True)
class HealthCondition:
    job_key: str
    kind: str
    severity: str
    summary: str
    fingerprint: str
    latest_run_key: str | None = None

    @property
    def incident_key(self) -> str:
        digest = hashlib.sha256(
            f"{self.job_key}|{self.kind}|{self.fingerprint}".encode()
        ).hexdigest()[:24]
        return f"{self.job_key}:{self.kind}:{digest}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_local_time(value: object) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    return time.fromisoformat(str(value))


def _latest_scheduled_at(job: Mapping[str, Any], now: datetime) -> datetime | None:
    schedule_type = str(job["schedule_type"])
    if schedule_type not in {"daily", "weekdays"}:
        return None
    local_time = _parse_local_time(job.get("schedule_local_time"))
    if local_time is None:
        return None
    try:
        timezone = ZoneInfo(str(job.get("schedule_timezone") or "UTC"))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid timezone for {job['job_key']}: {exc}") from exc
    local_now = _as_utc(now).astimezone(timezone)
    weekdays = {int(item) for item in (job.get("schedule_weekdays") or [])}
    for days_back in range(0, 8):
        candidate_date: date = local_now.date() - timedelta(days=days_back)
        if schedule_type == "weekdays" and candidate_date.isoweekday() not in weekdays:
            continue
        candidate = datetime.combine(candidate_date, local_time, tzinfo=timezone)
        if candidate <= local_now:
            return candidate.astimezone(UTC)
    return None


def evaluate_job(
    job: Mapping[str, Any],
    latest_run: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> list[HealthCondition]:
    """Evaluate one job without database side effects."""
    current = _as_utc(now or utc_now())
    job_key = str(job["job_key"])
    grace = timedelta(seconds=int(job.get("grace_seconds") or 0))
    stall = timedelta(seconds=int(job.get("stall_seconds") or 0))
    conditions: list[HealthCondition] = []

    if latest_run is not None:
        run_key = str(latest_run["run_key"])
        status = str(latest_run["status"])
        if status == "running":
            heartbeat = latest_run.get("heartbeat_at") or latest_run.get("started_at")
            if heartbeat is not None and current - _as_utc(heartbeat) > stall:
                summary = (
                    f"{job_key} has not sent a heartbeat since {_as_utc(heartbeat).isoformat()}"
                )
                conditions.append(
                    HealthCondition(job_key, "stalled", "error", summary, "stalled", run_key)
                )
        elif status in {"failed", "degraded"}:
            error = sanitize_text(latest_run.get("error_text") or status, max_chars=2_000)
            fingerprint = hashlib.sha256(f"{status}|{error[:500]}".encode()).hexdigest()[:24]
            severity = "error" if status == "failed" else "warning"
            conditions.append(
                HealthCondition(
                    job_key,
                    status,
                    severity,
                    f"{job_key} latest run is {status}: {error}",
                    fingerprint,
                    run_key,
                )
            )

    schedule_type = str(job["schedule_type"])
    latest_started = _as_utc(latest_run["started_at"]) if latest_run else None
    overdue = False
    expected_description = ""
    if schedule_type == "interval":
        interval = timedelta(seconds=int(job.get("schedule_interval_seconds") or 0))
        anchor = latest_started or _as_utc(job.get("enabled_at") or job["updated_at"])
        expected_at = anchor + interval
        overdue = current > expected_at + grace
        expected_description = expected_at.isoformat()
    elif schedule_type in {"daily", "weekdays"}:
        scheduled_at = _latest_scheduled_at(job, current)
        if scheduled_at is not None:
            overdue = current > scheduled_at + grace and (
                latest_started is None or latest_started < scheduled_at
            )
            expected_description = scheduled_at.isoformat()

    if overdue:
        conditions.append(
            HealthCondition(
                job_key,
                "overdue",
                "error",
                f"{job_key} has no run for schedule occurrence {expected_description}",
                "schedule",
                str(latest_run["run_key"]) if latest_run else None,
            )
        )
    return conditions


class PipelineOpsMonitor:
    """Materialize job health into a durable, leaseable incident queue."""

    def __init__(self, database_url: str, *, error_text_max_chars: int = 2_000) -> None:
        if not database_url:
            raise ValueError("pipeline ops database URL is required")
        self.database_url = database_url
        self.error_text_max_chars = max(256, int(error_text_max_chars))

    def doctor(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT current_database() AS database_name,
                       to_regnamespace('pipeline_ops') IS NOT NULL AS schema_exists,
                       to_regclass('pipeline_ops.jobs') IS NOT NULL AS jobs_exists,
                       to_regclass('pipeline_ops.incidents') IS NOT NULL AS incidents_exists
                """
            ).fetchone()
            assert row is not None
            return dict(row)

    def check(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current = _as_utc(now or utc_now())
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pipeline_ops.incidents i
                SET status = 'suppressed', resolved_at = %s,
                    resolution_summary = 'job disabled',
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = %s
                FROM pipeline_ops.jobs j
                WHERE i.job_key = j.job_key
                  AND NOT j.enabled
                  AND i.status IN ('open', 'claimed')
                """,
                (current, current),
            )
            rows = connection.execute(
                """
                SELECT j.*,
                       r.run_key AS latest_run_key,
                       r.status AS latest_run_status,
                       r.started_at AS latest_run_started_at,
                       r.heartbeat_at AS latest_run_heartbeat_at,
                       r.completed_at AS latest_run_completed_at,
                       r.error_text AS latest_run_error_text
                FROM pipeline_ops.jobs j
                LEFT JOIN LATERAL (
                    SELECT run_key, status, started_at, heartbeat_at,
                           completed_at, error_text
                    FROM pipeline_ops.runs
                    WHERE job_key = j.job_key AND status <> 'skipped'
                    ORDER BY started_at DESC
                    LIMIT 1
                ) r ON true
                WHERE j.enabled
                ORDER BY j.job_key
                """
            ).fetchall()
            observed_by_job: dict[str, set[str]] = {}
            for row in rows:
                job = dict(row)
                latest = None
                if row["latest_run_key"] is not None:
                    latest = {
                        "run_key": row["latest_run_key"],
                        "status": row["latest_run_status"],
                        "started_at": row["latest_run_started_at"],
                        "heartbeat_at": row["latest_run_heartbeat_at"],
                        "completed_at": row["latest_run_completed_at"],
                        "error_text": row["latest_run_error_text"],
                    }
                conditions = evaluate_job(job, latest, now=current)
                observed_by_job[job["job_key"]] = {
                    condition.incident_key for condition in conditions
                }
                for condition in conditions:
                    self._upsert_incident(connection, condition, current)
                self._resolve_absent_incidents(
                    connection,
                    job_key=str(job["job_key"]),
                    observed=observed_by_job[job["job_key"]],
                    resolved_at=current,
                )
            self._release_expired_claims(connection, current)
        return self.list_incidents(status="open", include_claimed=True)

    def list_incidents(
        self,
        *,
        status: str | None = None,
        include_claimed: bool = False,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in _INCIDENT_STATUSES:
            raise ValueError(f"invalid incident status: {status}")
        statuses: list[str]
        if status == "open" and include_claimed:
            statuses = ["open", "claimed"]
        elif status is None:
            statuses = list(_INCIDENT_STATUSES)
        else:
            statuses = [status]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.*, j.retry_policy, j.playbook_key, j.launchd_label
                FROM pipeline_ops.incidents i
                JOIN pipeline_ops.jobs j USING (job_key)
                WHERE i.status = ANY(%s)
                ORDER BY
                    CASE i.severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                    i.last_seen_at DESC
                """,
                (statuses,),
            ).fetchall()
            return [self._json_row(row) for row in rows]

    def claim(
        self,
        *,
        actor: str,
        limit: int = 5,
        lease_minutes: int = 20,
    ) -> list[dict[str, Any]]:
        if not actor.strip():
            raise ValueError("actor is required")
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT incident_key
                    FROM pipeline_ops.incidents
                    WHERE status = 'open'
                       OR (status = 'claimed' AND lease_expires_at < now())
                    ORDER BY
                        CASE severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
                        first_seen_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE pipeline_ops.incidents i
                SET status = 'claimed',
                    lease_owner = %s,
                    lease_expires_at = now() + make_interval(mins => %s),
                    updated_at = now()
                FROM candidates c
                WHERE i.incident_key = c.incident_key
                RETURNING i.*
                """,
                (max(1, int(limit)), actor, max(1, int(lease_minutes))),
            ).fetchall()
            return [self._json_row(row) for row in rows]

    def retry(
        self,
        *,
        incident_key: str,
        actor: str,
        dry_run: bool = False,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT i.*, j.retry_policy, j.launchd_label, j.playbook_key
                FROM pipeline_ops.incidents i
                JOIN pipeline_ops.jobs j USING (job_key)
                WHERE i.incident_key = %s
                FOR UPDATE
                """,
                (incident_key,),
            ).fetchone()
            if row is None:
                raise KeyError(f"incident not found: {incident_key}")
            if row["status"] not in {"open", "claimed"}:
                raise ValueError(f"incident is not actionable: {row['status']}")
            if row["retry_policy"] != "kickstart_once":
                return self._record_declined(
                    connection,
                    row,
                    actor=actor,
                    reason=f"retry policy is {row['retry_policy']}",
                    dry_run=dry_run,
                )
            label = str(row["launchd_label"] or "")
            if not _LAUNCHD_LABEL_RE.fullmatch(label):
                return self._record_declined(
                    connection,
                    row,
                    actor=actor,
                    reason="job has no valid allowlisted launchd label",
                    dry_run=dry_run,
                )
            prior = connection.execute(
                """
                SELECT 1
                FROM pipeline_ops.remediation_attempts
                WHERE incident_key = %s
                  AND action_key = 'launchd_kickstart'
                  AND status IN ('started', 'succeeded')
                  AND incident_occurrence = %s
                LIMIT 1
                """,
                (incident_key, row["occurrence_count"]),
            ).fetchone()
            if prior is not None:
                return self._record_declined(
                    connection,
                    row,
                    actor=actor,
                    reason="automatic retry already attempted for this incident occurrence",
                    dry_run=dry_run,
                )
            command = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]
            if dry_run:
                return {
                    "incident_key": incident_key,
                    "status": "dry_run",
                    "action_key": "launchd_kickstart",
                    "command": command,
                }
            attempt = connection.execute(
                """
                INSERT INTO pipeline_ops.remediation_attempts (
                    incident_key, job_key, incident_occurrence, actor,
                    action_key, status, details_json
                ) VALUES (%s, %s, %s, %s, 'launchd_kickstart', 'started', %s)
                RETURNING id
                """,
                (
                    incident_key,
                    row["job_key"],
                    row["occurrence_count"],
                    actor,
                    Jsonb({"launchd_label": label}),
                ),
            ).fetchone()
            assert attempt is not None
            attempt_id = int(attempt["id"])
            connection.commit()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_seconds)),
            )
            status = "succeeded" if completed.returncode == 0 else "failed"
            error_text = None if completed.returncode == 0 else completed.stderr or completed.stdout
            details = {"returncode": completed.returncode, "launchd_label": label}
        except (OSError, subprocess.TimeoutExpired) as exc:
            status = "failed"
            error_text = str(exc)
            details = {"launchd_label": label}
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pipeline_ops.remediation_attempts
                SET status = %s, completed_at = now(), details_json = %s,
                    error_text = %s
                WHERE id = %s
                """,
                (
                    status,
                    Jsonb(details),
                    sanitize_text(error_text, max_chars=self.error_text_max_chars)
                    if error_text
                    else None,
                    attempt_id,
                ),
            )
        return {
            "incident_key": incident_key,
            "attempt_id": attempt_id,
            "status": status,
            "action_key": "launchd_kickstart",
            "details": details,
        }

    def resolve(self, *, incident_key: str, actor: str, summary: str) -> dict[str, Any]:
        return self._set_incident_state(
            incident_key=incident_key,
            actor=actor,
            status="resolved",
            summary=summary,
        )

    def decline(self, *, incident_key: str, actor: str, reason: str) -> dict[str, Any]:
        return self._set_incident_state(
            incident_key=incident_key,
            actor=actor,
            status="suppressed",
            summary=reason,
        )

    def _set_incident_state(
        self,
        *,
        incident_key: str,
        actor: str,
        status: str,
        summary: str,
    ) -> dict[str, Any]:
        if status not in {"resolved", "suppressed"}:
            raise ValueError(f"unsupported terminal incident status: {status}")
        clean = sanitize_text(summary, max_chars=self.error_text_max_chars)
        with self._connect() as connection:
            row = connection.execute(
                """
                UPDATE pipeline_ops.incidents
                SET status = %s, resolution_summary = %s,
                    resolved_at = now(), lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = now()
                WHERE incident_key = %s
                RETURNING *
                """,
                (status, f"{actor}: {clean}", incident_key),
            ).fetchone()
            if row is None:
                raise KeyError(f"incident not found: {incident_key}")
            return self._json_row(row)

    @staticmethod
    def _upsert_incident(
        connection: psycopg.Connection[dict[str, Any]],
        condition: HealthCondition,
        seen_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO pipeline_ops.incidents (
                incident_key, job_key, latest_run_key, kind, severity,
                fingerprint, summary, status, first_seen_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s, %s)
            ON CONFLICT (incident_key) DO UPDATE SET
                latest_run_key = EXCLUDED.latest_run_key,
                severity = EXCLUDED.severity,
                summary = EXCLUDED.summary,
                status = CASE
                    WHEN pipeline_ops.incidents.status IN ('resolved', 'suppressed')
                    THEN 'open'
                    ELSE pipeline_ops.incidents.status
                END,
                occurrence_count = pipeline_ops.incidents.occurrence_count + CASE
                    WHEN pipeline_ops.incidents.status IN ('resolved', 'suppressed') THEN 1
                    WHEN pipeline_ops.incidents.latest_run_key
                        IS DISTINCT FROM EXCLUDED.latest_run_key
                    THEN 1 ELSE 0 END,
                last_seen_at = EXCLUDED.last_seen_at,
                resolved_at = CASE
                    WHEN pipeline_ops.incidents.status IN ('resolved', 'suppressed')
                    THEN NULL ELSE pipeline_ops.incidents.resolved_at END,
                resolution_summary = CASE
                    WHEN pipeline_ops.incidents.status IN ('resolved', 'suppressed')
                    THEN NULL ELSE pipeline_ops.incidents.resolution_summary END,
                updated_at = EXCLUDED.last_seen_at
            """,
            (
                condition.incident_key,
                condition.job_key,
                condition.latest_run_key,
                condition.kind,
                condition.severity,
                condition.fingerprint,
                condition.summary,
                seen_at,
                seen_at,
            ),
        )

    @staticmethod
    def _resolve_absent_incidents(
        connection: psycopg.Connection[dict[str, Any]],
        *,
        job_key: str,
        observed: set[str],
        resolved_at: datetime,
    ) -> None:
        if observed:
            connection.execute(
                """
                UPDATE pipeline_ops.incidents
                SET status = 'resolved', resolved_at = %s,
                    resolution_summary = 'superseded by current healthy state',
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = %s
                WHERE job_key = %s
                  AND status IN ('open', 'claimed')
                  AND NOT (incident_key = ANY(%s))
                """,
                (resolved_at, resolved_at, job_key, list(observed)),
            )
        else:
            connection.execute(
                """
                UPDATE pipeline_ops.incidents
                SET status = 'resolved', resolved_at = %s,
                    resolution_summary = 'superseded by current healthy state',
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = %s
                WHERE job_key = %s AND status IN ('open', 'claimed')
                """,
                (resolved_at, resolved_at, job_key),
            )

    @staticmethod
    def _release_expired_claims(
        connection: psycopg.Connection[dict[str, Any]], current: datetime
    ) -> None:
        connection.execute(
            """
            UPDATE pipeline_ops.incidents
            SET status = 'open', lease_owner = NULL, lease_expires_at = NULL,
                updated_at = %s
            WHERE status = 'claimed' AND lease_expires_at < %s
            """,
            (current, current),
        )

    def _record_declined(
        self,
        connection: psycopg.Connection[dict[str, Any]],
        incident: Mapping[str, Any],
        *,
        actor: str,
        reason: str,
        dry_run: bool,
    ) -> dict[str, Any]:
        result = {
            "incident_key": incident["incident_key"],
            "status": "declined",
            "action_key": "none",
            "reason": reason,
            "dry_run": dry_run,
        }
        if dry_run:
            return result
        connection.execute(
            """
            INSERT INTO pipeline_ops.remediation_attempts (
                incident_key, job_key, incident_occurrence, actor,
                action_key, status, completed_at, error_text
            ) VALUES (%s, %s, %s, %s, 'none', 'declined', now(), %s)
            """,
            (
                incident["incident_key"],
                incident["job_key"],
                incident["occurrence_count"],
                actor,
                reason,
            ),
        )
        return result

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _json_row(row: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                result[key] = value.astimezone(UTC).isoformat()
            elif isinstance(value, date):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result


def json_dump(value: object) -> str:
    if isinstance(value, HealthCondition):
        value = asdict(value) | {"incident_key": value.incident_key}
    return json.dumps(value, indent=2, sort_keys=True, default=str)
