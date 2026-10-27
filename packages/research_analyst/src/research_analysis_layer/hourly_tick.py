"""One bounded analyst hourly tick with centralized operations telemetry."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from research_pipeline_ops import PipelineOpsClient


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _setting(name: str, default: int) -> int:
    prefixed = f"RESEARCH_ANALYST_{name}"
    return int(os.getenv(prefixed, os.getenv(name, str(default))))


def _json_object(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("analyst child command did not return a JSON object")


def _run_child(
    arguments: list[str],
    *,
    env: dict[str, str],
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    completed = runner(
        [sys.executable, "-m", "research_analysis_layer.main", *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed


def run_tick(*, runner: Runner = subprocess.run, ops: PipelineOpsClient | None = None) -> int:
    batch_limit = _setting("RUN_BATCH_LIMIT", 25)
    max_batches = _setting("MAX_BATCHES_PER_TICK", 8)
    forecast_limit = _setting("FORECAST_UPLOAD_LIMIT", 250)
    if min(batch_limit, max_batches, forecast_limit) < 1:
        raise ValueError("hourly tick limits must be positive")

    if ops is None:
        spool_path = Path(
            os.getenv(
                "RESEARCH_ANALYST_PIPELINE_OPS_SPOOL",
                "data/pipeline_ops_spool.db",
            )
        ).expanduser()
        ops = PipelineOpsClient.from_env(
            default_spool_db_path=spool_path,
            emitted_by="research_analyst",
        )
    ops.flush()
    run_key = ops.start_run(
        job_key="analyst.hourly",
        repo_name="research_analyst",
        stage_family="analyst",
        run_type="hourly",
        trigger_source=os.getenv("PIPELINE_OPS_TRIGGER_SOURCE", "hourly_runner"),
    )
    child_env = dict(os.environ)
    if run_key is not None:
        child_env["PIPELINE_OPS_PARENT_RUN_KEY"] = run_key

    totals = {
        "batch_count": 0,
        "document_count": 0,
        "success_count": 0,
        "skipped_count": 0,
        "error_count": 0,
    }
    status = "succeeded"
    exit_code = 0
    error_text: str | None = None
    try:
        for batch_number in range(1, max_batches + 1):
            completed = _run_child(
                ["run", "--limit", str(batch_limit)],
                env=child_env,
                runner=runner,
            )
            try:
                report = _json_object(completed.stdout)
            except ValueError:
                report = {}
            totals["batch_count"] = batch_number
            for key in ("document_count", "success_count", "skipped_count", "error_count"):
                totals[key] += int(report.get(key, 0))
            ops.heartbeat(run_key, stats=totals)

            if completed.returncode != 0:
                status = "degraded" if report else "failed"
                exit_code = completed.returncode
                error_text = "analysis_batch_failed"
                break
            if int(report.get("document_count", 0)) < batch_limit:
                break

        if exit_code == 0:
            forecast = _run_child(
                ["sync-forecasts", "--upload-limit", str(forecast_limit)],
                env=child_env,
                runner=runner,
            )
            totals["forecast_sync_exit_code"] = forecast.returncode
            if forecast.returncode != 0:
                status = "degraded"
                error_text = "forecast_sync_failed"
    except Exception as exc:
        print(f"hourly tick failed: {exc}", file=sys.stderr)
        status = "failed"
        exit_code = 1
        error_text = exc.__class__.__name__
    finally:
        ops.finish_run(
            run_key,
            status=status,
            stats=totals,
            error_text=error_text,
            exit_code=exit_code,
        )
        ops.flush()
    return exit_code


def main() -> int:
    return run_tick()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
