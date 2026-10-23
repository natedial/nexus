import json
import subprocess

from research_analysis_layer.hourly_tick import run_tick


class FakeOps:
    def __init__(self):
        self.heartbeats = []
        self.finished = []
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        return 0

    def start_run(self, **kwargs):
        assert kwargs["job_key"] == "analyst.hourly"
        return "analyst:test-run"

    def heartbeat(self, run_key, **kwargs):
        self.heartbeats.append((run_key, kwargs))

    def finish_run(self, run_key, **kwargs):
        self.finished.append((run_key, kwargs))


def _completed(payload, returncode=0):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_hourly_tick_records_parent_run_and_heartbeat(monkeypatch):
    monkeypatch.setenv("RESEARCH_ANALYST_RUN_BATCH_LIMIT", "2")
    monkeypatch.setenv("RESEARCH_ANALYST_MAX_BATCHES_PER_TICK", "3")
    monkeypatch.setenv("RESEARCH_ANALYST_FORECAST_UPLOAD_LIMIT", "5")
    calls = []
    results = [
        _completed(
            {
                "document_count": 1,
                "success_count": 1,
                "skipped_count": 0,
                "error_count": 0,
            }
        ),
        _completed({"upload": {"failed_count": 0}}),
    ]

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return results.pop(0)

    ops = FakeOps()
    assert run_tick(runner=runner, ops=ops) == 0

    assert calls[0][1]["env"]["PIPELINE_OPS_PARENT_RUN_KEY"] == "analyst:test-run"
    assert calls[0][0][-3:] == ["run", "--limit", "2"]
    assert calls[1][0][-3:] == ["sync-forecasts", "--upload-limit", "5"]
    assert ops.heartbeats[-1][1]["stats"]["document_count"] == 1
    assert ops.finished[-1][1]["status"] == "succeeded"
    assert ops.flush_count == 2


def test_hourly_tick_records_document_errors_as_degraded(monkeypatch):
    monkeypatch.setenv("RESEARCH_ANALYST_RUN_BATCH_LIMIT", "2")
    monkeypatch.setenv("RESEARCH_ANALYST_MAX_BATCHES_PER_TICK", "3")
    monkeypatch.setenv("RESEARCH_ANALYST_FORECAST_UPLOAD_LIMIT", "5")

    def runner(_arguments, **_kwargs):
        return _completed(
            {
                "document_count": 1,
                "success_count": 0,
                "skipped_count": 0,
                "error_count": 1,
            },
            returncode=1,
        )

    ops = FakeOps()
    assert run_tick(runner=runner, ops=ops) == 1

    terminal = ops.finished[-1][1]
    assert terminal["status"] == "degraded"
    assert terminal["stats"]["error_count"] == 1
    assert terminal["error_text"] == "analysis_batch_failed"
