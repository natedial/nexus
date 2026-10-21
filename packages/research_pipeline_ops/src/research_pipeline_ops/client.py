"""PostgreSQL-backed operational event client with an idempotent SQLite spool."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

RUN_STATUSES = frozenset({"running", "succeeded", "degraded", "failed", "skipped"})
STAGE_STATUSES = frozenset(
    {"queued", "started", "heartbeat", "succeeded", "failed", "skipped", "retrying", "stalled"}
)
MODES = frozenset({"required", "best_effort", "off"})
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|access[_-]?key)\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIAL_RE = re.compile(r"(://[^:/\s]+:)([^@/\s]+)(@)")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_DOCUMENT_FIELDS = frozenset(
    {
        "document_name",
        "source",
        "source_date",
        "publisher",
        "region",
        "asset_focus",
        "parser_updated_at",
    }
)


class PipelineOpsError(RuntimeError):
    """Base error for pipeline operations."""


class PipelineOpsConfigurationError(PipelineOpsError):
    """Raised when the client is configured unsafely or incompletely."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_document_key(
    *,
    file_id: str | None = None,
    research_id: int | None = None,
    document_hash: str | None = None,
) -> str:
    """Build the canonical document identity used by pipeline_ops."""
    if file_id:
        return f"file:{file_id}"
    if research_id is not None and document_hash:
        return f"doc:{research_id}:{document_hash}"
    if research_id is not None:
        return f"research:{research_id}"
    if document_hash:
        return f"hash:{document_hash}"
    raise ValueError("file_id, research_id, or document_hash is required")


def sanitize_text(value: object, *, max_chars: int) -> str:
    """Remove common credential shapes and bound operational text."""
    text = _CONTROL_RE.sub("", str(value))
    text = _URL_CREDENTIAL_RE.sub(r"\1[redacted]\3", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return text[:max_chars]


def _json_value(value: Any, *, max_chars: int, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("operational payload nesting exceeds 8 levels")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value, max_chars=max_chars)
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("operational payload keys must be strings")
            result[sanitize_text(key, max_chars=120)] = _json_value(
                item, max_chars=max_chars, depth=depth + 1
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_json_value(item, max_chars=max_chars, depth=depth + 1) for item in value]
    raise TypeError(f"unsupported operational payload type: {type(value).__name__}")


class PipelineOpsClient:
    """Write operational events without making telemetry a domain dependency.

    Transport failures spool in ``best_effort`` mode. Validation errors always
    raise because they are programming errors, not availability failures.
    """

    def __init__(
        self,
        *,
        database_url: str | None,
        spool_db_path: str | Path,
        emitted_by: str,
        mode: str = "best_effort",
        error_text_max_chars: int = 2_000,
        spool_max_rows: int = 50_000,
        connect_timeout_seconds: int = 5,
    ) -> None:
        if mode not in MODES:
            raise PipelineOpsConfigurationError(
                f"invalid PIPELINE_OPS_MODE {mode!r}; choose {', '.join(sorted(MODES))}"
            )
        if mode == "required" and not database_url:
            raise PipelineOpsConfigurationError(
                "PIPELINE_OPS_DATABASE_URL or NEXUS_DATABASE_URL is required"
            )
        self.database_url = database_url
        self.spool_db_path = Path(spool_db_path).expanduser()
        self.emitted_by = self._identifier(emitted_by, "emitted_by")
        self.mode = mode
        self.error_text_max_chars = max(256, int(error_text_max_chars))
        self.spool_max_rows = max(1, int(spool_max_rows))
        self.connect_timeout_seconds = max(1, int(connect_timeout_seconds))

    @classmethod
    def from_env(
        cls,
        *,
        default_spool_db_path: str | Path,
        emitted_by: str,
    ) -> PipelineOpsClient:
        database_url = os.getenv("PIPELINE_OPS_DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL")
        return cls(
            database_url=database_url,
            spool_db_path=default_spool_db_path,
            emitted_by=emitted_by,
            mode=os.getenv("PIPELINE_OPS_MODE", "best_effort").strip().lower(),
            error_text_max_chars=int(os.getenv("PIPELINE_OPS_ERROR_TEXT_MAX_CHARS", "2000")),
            spool_max_rows=int(os.getenv("PIPELINE_OPS_SPOOL_MAX_ROWS", "50000")),
            connect_timeout_seconds=int(os.getenv("PIPELINE_OPS_CONNECT_TIMEOUT_SECONDS", "5")),
        )

    def start_run(
        self,
        *,
        job_key: str | None = None,
        repo_name: str | None = None,
        stage_family: str | None = None,
        run_type: str | None = None,
        trigger_source: str | None = None,
        batch_key: str | None = None,
        analysis_version: str | None = None,
        stats: Mapping[str, Any] | None = None,
        run_key: str | None = None,
        started_at: datetime | None = None,
        worker_id: str | None = None,
    ) -> str | None:
        if self.mode == "off":
            return None
        if job_key:
            self._identifier(job_key, "job_key")
        repo_name = repo_name or (job_key.split(".", 1)[0] if job_key else None)
        run_type = run_type or (job_key.split(".", 1)[1] if job_key and "." in job_key else None)
        stage_family = stage_family or repo_name
        if not repo_name or not stage_family or not run_type:
            raise ValueError("job_key or repo_name, stage_family, and run_type are required")
        started = (started_at or utc_now()).astimezone(UTC)
        key = run_key or (
            f"{job_key or repo_name}:{started.strftime('%Y%m%dT%H%M%S')}:{uuid.uuid4().hex}"
        )
        payload = {
            "run_key": self._identifier(key, "run_key"),
            "job_key": job_key,
            "repo_name": self._identifier(repo_name, "repo_name"),
            "stage_family": self._identifier(stage_family, "stage_family"),
            "run_type": self._identifier(run_type, "run_type"),
            "status": "running",
            "host": socket.gethostname(),
            "worker_id": worker_id,
            "trigger_source": trigger_source,
            "batch_key": batch_key,
            "analysis_version": analysis_version,
            "started_at": started.isoformat(),
            "stats": self._payload(stats or {}),
        }
        self._submit("start_run", payload)
        return key

    def heartbeat(
        self,
        run_key: str | None,
        *,
        stats: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if self.mode == "off" or run_key is None:
            return
        self._submit(
            "heartbeat",
            {
                "run_key": self._identifier(run_key, "run_key"),
                "occurred_at": (occurred_at or utc_now()).astimezone(UTC).isoformat(),
                "stats": self._payload(stats or {}),
            },
        )

    def finish_run(
        self,
        run_key: str | None,
        *,
        status: str,
        stats: Mapping[str, Any] | None = None,
        error_text: str | None = None,
        exit_code: int | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        if status not in RUN_STATUSES - {"running"}:
            raise ValueError(f"invalid terminal run status: {status}")
        if self.mode == "off" or run_key is None:
            return
        self._submit(
            "finish_run",
            {
                "run_key": self._identifier(run_key, "run_key"),
                "status": status,
                "stats": self._payload(stats or {}),
                "error_text": self._error(error_text),
                "exit_code": exit_code,
                "completed_at": (completed_at or utc_now()).astimezone(UTC).isoformat(),
            },
        )

    def update_run(
        self,
        run_key: str | None,
        *,
        status: str,
        stats: Mapping[str, Any] | None = None,
        error_text: str | None = None,
        completed: bool = False,
        exit_code: int | None = None,
    ) -> None:
        """Backward-compatible facade for existing producer instrumentation."""
        normalized = {"completed": "succeeded", "error": "failed"}.get(status, status)
        if completed or normalized in RUN_STATUSES - {"running"}:
            self.finish_run(
                run_key,
                status=normalized,
                stats=stats,
                error_text=error_text,
                exit_code=exit_code,
            )
            return
        if normalized != "running":
            raise ValueError(f"invalid run status: {status}")
        self.heartbeat(run_key, stats=stats)

    def emit_stage_event(
        self,
        *,
        repo_name: str,
        stage_name: str,
        status: str,
        run_key: str | None = None,
        document_key: str | None = None,
        file_id: str | None = None,
        research_id: int | None = None,
        document_hash: str | None = None,
        attempt: int | None = None,
        duration_ms: int | None = None,
        queue_lag_ms: int | None = None,
        payload: Mapping[str, Any] | None = None,
        document_fields: Mapping[str, Any] | None = None,
        error_type: str | None = None,
        error_text: str | None = None,
        occurred_at: datetime | None = None,
        event_key: str | None = None,
    ) -> str | None:
        if status not in STAGE_STATUSES:
            raise ValueError(f"invalid stage status: {status}")
        if self.mode == "off":
            return None
        fields = self._payload(document_fields or {})
        unknown_fields = set(fields) - _DOCUMENT_FIELDS
        if unknown_fields:
            raise ValueError(f"unsupported document fields: {', '.join(sorted(unknown_fields))}")
        key = event_key or uuid.uuid4().hex
        body = {
            "event_key": self._identifier(key, "event_key"),
            "occurred_at": (occurred_at or utc_now()).astimezone(UTC).isoformat(),
            "repo_name": self._identifier(repo_name, "repo_name"),
            "stage_name": self._identifier(stage_name, "stage_name"),
            "status": status,
            "document_key": document_key,
            "run_key": run_key,
            "file_id": file_id,
            "research_id": research_id,
            "document_hash": document_hash,
            "attempt": attempt,
            "duration_ms": duration_ms,
            "queue_lag_ms": queue_lag_ms,
            "payload": self._payload(payload or {}),
            **{field: fields.get(field) for field in _DOCUMENT_FIELDS},
            "error_type": self._error(error_type),
            "error_text": self._error(error_text),
            "emitted_by": self.emitted_by,
        }
        self._submit("stage_event", body)
        return key

    @contextmanager
    def track_stage(
        self,
        *,
        repo_name: str,
        stage_name: str,
        run_key: str | None = None,
        document_key: str | None = None,
        file_id: str | None = None,
        research_id: int | None = None,
        document_hash: str | None = None,
        payload: Mapping[str, Any] | None = None,
        document_fields: Mapping[str, Any] | None = None,
        attempt: int | None = None,
    ) -> Iterator[None]:
        started = time.monotonic()
        self.emit_stage_event(
            repo_name=repo_name,
            stage_name=stage_name,
            status="started",
            run_key=run_key,
            document_key=document_key,
            file_id=file_id,
            research_id=research_id,
            document_hash=document_hash,
            payload=payload,
            document_fields=document_fields,
            attempt=attempt,
        )
        try:
            yield
        except Exception as exc:
            self.emit_stage_event(
                repo_name=repo_name,
                stage_name=stage_name,
                status="failed",
                run_key=run_key,
                document_key=document_key,
                file_id=file_id,
                research_id=research_id,
                document_hash=document_hash,
                payload=payload,
                document_fields=document_fields,
                attempt=attempt,
                duration_ms=round((time.monotonic() - started) * 1000),
                error_type=exc.__class__.__name__,
                error_text=str(exc),
            )
            raise
        else:
            self.emit_stage_event(
                repo_name=repo_name,
                stage_name=stage_name,
                status="succeeded",
                run_key=run_key,
                document_key=document_key,
                file_id=file_id,
                research_id=research_id,
                document_hash=document_hash,
                payload=payload,
                document_fields=document_fields,
                attempt=attempt,
                duration_ms=round((time.monotonic() - started) * 1000),
            )

    def flush(self, *, limit: int = 1_000) -> int:
        if self.mode == "off" or not self.database_url or not self.spool_db_path.exists():
            return 0
        flushed = 0
        with self._spool_connection() as spool:
            rows = spool.execute(
                """
                SELECT id, op_key, op_type, payload_json
                FROM spool_operations
                ORDER BY id
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            for row_id, op_key, op_type, payload_json in rows:
                envelope = {
                    "op_key": op_key,
                    "op_type": op_type,
                    "payload": json.loads(payload_json),
                }
                try:
                    self._apply_envelope(envelope)
                except Exception as exc:  # keep ordering; a dependency may be missing
                    spool.execute(
                        """
                        UPDATE spool_operations
                        SET attempts = attempts + 1, last_error = ?
                        WHERE id = ?
                        """,
                        (self._error(exc), row_id),
                    )
                    spool.commit()
                    if self.mode == "required":
                        raise
                    log.error("pipeline ops spool replay stopped: %s", self._error(exc))
                    break
                spool.execute("DELETE FROM spool_operations WHERE id = ?", (row_id,))
                spool.commit()
                flushed += 1
        return flushed

    def spool_depth(self) -> int:
        if not self.spool_db_path.exists():
            return 0
        with self._spool_connection() as spool:
            row = spool.execute("SELECT count(*) FROM spool_operations").fetchone()
            return int(row[0]) if row else 0

    def _submit(self, op_type: str, payload: Mapping[str, Any]) -> None:
        envelope = {
            "op_key": uuid.uuid4().hex,
            "op_type": op_type,
            "payload": dict(payload),
        }
        if self.spool_depth() > 0:
            self._spool(envelope, "queued behind existing spool backlog")
            self.flush()
            return
        if not self.database_url:
            if self.mode == "required":
                raise PipelineOpsConfigurationError("pipeline ops database URL is not configured")
            self._spool(envelope, "database URL is not configured")
            return
        try:
            self._apply_envelope(envelope)
        except Exception as exc:
            if self.mode == "required":
                raise
            self._spool(envelope, exc)

    def _apply_envelope(self, envelope: Mapping[str, Any]) -> None:
        if not self.database_url:
            raise PipelineOpsConfigurationError("pipeline ops database URL is not configured")
        with psycopg.connect(
            self.database_url,
            connect_timeout=self.connect_timeout_seconds,
            application_name=f"nexus_ops:{self.emitted_by}",
        ) as connection:
            with connection.cursor() as cursor:
                inserted = cursor.execute(
                    """
                    INSERT INTO pipeline_ops.ingested_operations
                        (operation_key, operation_type, emitted_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (operation_key) DO NOTHING
                    RETURNING operation_key
                    """,
                    (envelope["op_key"], envelope["op_type"], self.emitted_by),
                ).fetchone()
                if inserted is None:
                    return
                operation = str(envelope["op_type"])
                payload = dict(envelope["payload"])
                if operation == "start_run":
                    self._apply_start_run(cursor, payload)
                elif operation == "heartbeat":
                    self._apply_heartbeat(cursor, payload)
                elif operation == "finish_run":
                    self._apply_finish_run(cursor, payload)
                elif operation == "stage_event":
                    self._apply_stage_event(cursor, payload)
                else:
                    raise ValueError(f"unknown pipeline ops operation: {operation}")

    @staticmethod
    def _apply_start_run(cursor: psycopg.Cursor[Any], payload: Mapping[str, Any]) -> None:
        cursor.execute(
            """
            INSERT INTO pipeline_ops.runs (
                run_key, job_key, repo_name, stage_family, run_type, status,
                host, worker_id, trigger_source, batch_key, analysis_version,
                started_at, heartbeat_at, stats_json
            ) VALUES (
                %(run_key)s, %(job_key)s, %(repo_name)s, %(stage_family)s,
                %(run_type)s, %(status)s, %(host)s, %(worker_id)s,
                %(trigger_source)s, %(batch_key)s, %(analysis_version)s,
                %(started_at)s, %(started_at)s, %(stats)s
            )
            ON CONFLICT (run_key) DO NOTHING
            """,
            {**payload, "stats": Jsonb(payload["stats"])},
        )

    @staticmethod
    def _apply_heartbeat(cursor: psycopg.Cursor[Any], payload: Mapping[str, Any]) -> None:
        cursor.execute(
            """
            UPDATE pipeline_ops.runs
            SET heartbeat_at = %(occurred_at)s,
                updated_at = %(occurred_at)s,
                stats_json = stats_json || %(stats)s
            WHERE run_key = %(run_key)s
            """,
            {**payload, "stats": Jsonb(payload["stats"])},
        )
        if cursor.rowcount != 1:
            raise PipelineOpsError(f"cannot heartbeat missing run {payload['run_key']}")

    @staticmethod
    def _apply_finish_run(cursor: psycopg.Cursor[Any], payload: Mapping[str, Any]) -> None:
        cursor.execute(
            """
            UPDATE pipeline_ops.runs
            SET status = %(status)s,
                stats_json = stats_json || %(stats)s,
                error_text = %(error_text)s,
                exit_code = %(exit_code)s,
                completed_at = %(completed_at)s,
                heartbeat_at = %(completed_at)s,
                updated_at = %(completed_at)s
            WHERE run_key = %(run_key)s
            """,
            {**payload, "stats": Jsonb(payload["stats"])},
        )
        if cursor.rowcount != 1:
            raise PipelineOpsError(f"cannot finish missing run {payload['run_key']}")

    @staticmethod
    def _apply_stage_event(cursor: psycopg.Cursor[Any], payload: Mapping[str, Any]) -> None:
        inserted = cursor.execute(
            """
            INSERT INTO pipeline_ops.stage_events (
                event_key, occurred_at, repo_name, stage_name, status,
                document_key, run_key, file_id, research_id, document_hash,
                attempt, duration_ms, queue_lag_ms, payload_json,
                error_type, error_text, emitted_by
            ) VALUES (
                %(event_key)s, %(occurred_at)s, %(repo_name)s, %(stage_name)s,
                %(status)s, %(document_key)s, %(run_key)s, %(file_id)s,
                %(research_id)s, %(document_hash)s, %(attempt)s, %(duration_ms)s,
                %(queue_lag_ms)s, %(payload)s, %(error_type)s, %(error_text)s,
                %(emitted_by)s
            )
            ON CONFLICT (event_key) DO NOTHING
            RETURNING id
            """,
            {**payload, "payload": Jsonb(payload["payload"])},
        ).fetchone()
        if inserted is None:
            return
        if payload.get("document_key"):
            cursor.execute(
                """
                INSERT INTO pipeline_ops.documents (
                    document_key, file_id, research_id, document_hash,
                    document_name, source, source_date, publisher, region,
                    asset_focus, parser_updated_at, updated_at
                ) VALUES (
                    %(document_key)s, %(file_id)s, %(research_id)s,
                    %(document_hash)s,
                    %(document_name)s, %(source)s, %(source_date)s,
                    %(publisher)s, %(region)s, %(asset_focus)s,
                    COALESCE(
                        %(parser_updated_at)s::timestamptz,
                        CASE WHEN %(repo_name)s = 'research_parser'
                            THEN %(occurred_at)s::timestamptz END
                    ),
                    %(occurred_at)s
                )
                ON CONFLICT (document_key) DO UPDATE SET
                    file_id = COALESCE(EXCLUDED.file_id, pipeline_ops.documents.file_id),
                    research_id = COALESCE(
                        EXCLUDED.research_id,
                        pipeline_ops.documents.research_id
                    ),
                    document_hash = COALESCE(
                        EXCLUDED.document_hash,
                        pipeline_ops.documents.document_hash
                    ),
                    document_name = COALESCE(
                        EXCLUDED.document_name,
                        pipeline_ops.documents.document_name
                    ),
                    source = COALESCE(EXCLUDED.source, pipeline_ops.documents.source),
                    source_date = COALESCE(
                        EXCLUDED.source_date,
                        pipeline_ops.documents.source_date
                    ),
                    publisher = COALESCE(
                        EXCLUDED.publisher,
                        pipeline_ops.documents.publisher
                    ),
                    region = COALESCE(EXCLUDED.region, pipeline_ops.documents.region),
                    asset_focus = COALESCE(
                        EXCLUDED.asset_focus,
                        pipeline_ops.documents.asset_focus
                    ),
                    parser_updated_at = COALESCE(
                        EXCLUDED.parser_updated_at,
                        pipeline_ops.documents.parser_updated_at
                    ),
                    updated_at = %(occurred_at)s
                """,
                payload,
            )
            cursor.execute(
                """
                INSERT INTO pipeline_ops.document_stage_state (
                    document_key, stage_name, repo_name, current_status,
                    last_event_at, last_success_at, last_failure_at,
                    attempt_count, latest_run_key, latest_duration_ms,
                    latest_queue_lag_ms, error_type, error_text, payload_json
                ) VALUES (
                    %(document_key)s, %(stage_name)s, %(repo_name)s, %(status)s,
                    %(occurred_at)s,
                    CASE WHEN %(status)s = 'succeeded' THEN %(occurred_at)s::timestamptz END,
                    CASE WHEN %(status)s = 'failed' THEN %(occurred_at)s::timestamptz END,
                    COALESCE(%(attempt)s, 1), %(run_key)s, %(duration_ms)s,
                    %(queue_lag_ms)s, %(error_type)s, %(error_text)s, %(payload)s
                )
                ON CONFLICT (document_key, stage_name) DO UPDATE SET
                    repo_name = EXCLUDED.repo_name,
                    current_status = EXCLUDED.current_status,
                    last_event_at = EXCLUDED.last_event_at,
                    last_success_at = COALESCE(EXCLUDED.last_success_at,
                        pipeline_ops.document_stage_state.last_success_at),
                    last_failure_at = COALESCE(EXCLUDED.last_failure_at,
                        pipeline_ops.document_stage_state.last_failure_at),
                    attempt_count = GREATEST(
                        pipeline_ops.document_stage_state.attempt_count,
                        EXCLUDED.attempt_count
                    ),
                    latest_run_key = EXCLUDED.latest_run_key,
                    latest_duration_ms = EXCLUDED.latest_duration_ms,
                    latest_queue_lag_ms = EXCLUDED.latest_queue_lag_ms,
                    error_type = EXCLUDED.error_type,
                    error_text = EXCLUDED.error_text,
                    payload_json = EXCLUDED.payload_json
                """,
                {**payload, "payload": Jsonb(payload["payload"])},
            )
        if payload.get("run_key"):
            cursor.execute(
                """
                INSERT INTO pipeline_ops.run_stage_state (
                    run_key, stage_name, repo_name, current_status,
                    started_at, completed_at, processed_count, success_count,
                    failed_count, skipped_count, avg_duration_ms,
                    p95_duration_ms, payload_json
                ) VALUES (
                    %(run_key)s, %(stage_name)s, %(repo_name)s, %(status)s,
                    CASE WHEN %(status)s = 'started' THEN %(occurred_at)s::timestamptz END,
                    CASE WHEN %(status)s IN ('succeeded', 'failed', 'skipped')
                        THEN %(occurred_at)s::timestamptz END,
                    CASE WHEN %(status)s IN ('succeeded', 'failed', 'skipped') THEN 1 ELSE 0 END,
                    CASE WHEN %(status)s = 'succeeded' THEN 1 ELSE 0 END,
                    CASE WHEN %(status)s = 'failed' THEN 1 ELSE 0 END,
                    CASE WHEN %(status)s = 'skipped' THEN 1 ELSE 0 END,
                    %(duration_ms)s, %(duration_ms)s, %(payload)s
                )
                ON CONFLICT (run_key, stage_name) DO UPDATE SET
                    current_status = EXCLUDED.current_status,
                    started_at = COALESCE(
                        pipeline_ops.run_stage_state.started_at,
                        EXCLUDED.started_at
                    ),
                    completed_at = COALESCE(
                        EXCLUDED.completed_at,
                        pipeline_ops.run_stage_state.completed_at
                    ),
                    processed_count = pipeline_ops.run_stage_state.processed_count
                        + EXCLUDED.processed_count,
                    success_count = pipeline_ops.run_stage_state.success_count
                        + EXCLUDED.success_count,
                    failed_count = pipeline_ops.run_stage_state.failed_count
                        + EXCLUDED.failed_count,
                    skipped_count = pipeline_ops.run_stage_state.skipped_count
                        + EXCLUDED.skipped_count,
                    avg_duration_ms = EXCLUDED.avg_duration_ms,
                    p95_duration_ms = EXCLUDED.p95_duration_ms,
                    payload_json = EXCLUDED.payload_json
                """,
                {**payload, "payload": Jsonb(payload["payload"])},
            )

    def _spool(self, envelope: Mapping[str, Any], error: object) -> None:
        try:
            with self._spool_connection() as spool:
                count = int(spool.execute("SELECT count(*) FROM spool_operations").fetchone()[0])
                if count >= self.spool_max_rows:
                    log.error(
                        "pipeline ops spool is full path=%s rows=%s error=%s",
                        self.spool_db_path,
                        count,
                        self._error(error),
                    )
                    return
                spool.execute(
                    """
                    INSERT OR IGNORE INTO spool_operations (
                        op_key, op_type, payload_json, created_at, last_error
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        envelope["op_key"],
                        envelope["op_type"],
                        json.dumps(envelope["payload"], sort_keys=True),
                        utc_now().isoformat(),
                        self._error(error),
                    ),
                )
                spool.commit()
        except Exception as spool_exc:
            log.error(
                "pipeline ops write and spool both failed database_error=%s spool_error=%s",
                self._error(error),
                self._error(spool_exc),
            )

    @contextmanager
    def _spool_connection(self) -> Iterator[sqlite3.Connection]:
        self.spool_db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.spool_db_path, timeout=10)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spool_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    op_key TEXT NOT NULL UNIQUE,
                    op_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            yield connection
        finally:
            connection.close()

    def _payload(self, value: Mapping[str, Any]) -> dict[str, Any]:
        result = _json_value(value, max_chars=self.error_text_max_chars)
        if not isinstance(result, dict):  # pragma: no cover - Mapping guarantees this
            raise TypeError("operational payload must be an object")
        return result

    def _error(self, value: object | None) -> str | None:
        if value is None:
            return None
        return sanitize_text(value, max_chars=self.error_text_max_chars)

    @staticmethod
    def _identifier(value: str, field: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"invalid {field}: {value!r}")
        return value
