from src.main import ResearchParserService


class FakeOps:
    def __init__(self):
        self.finished = []
        self.flush_count = 0

    def start_run(self, **kwargs):
        assert kwargs["job_key"] == "parser.poll"
        return "parser:test-run"

    def finish_run(self, run_key, **kwargs):
        self.finished.append((run_key, kwargs))

    def flush(self):
        self.flush_count += 1


class FakePipeline:
    def __init__(self, *, processed=2, failed=0):
        self.processed = processed
        self.ops_failed_count = failed
        self.run_keys = []

    def begin_ops_run(self, run_key):
        self.run_keys.append(run_key)

    def run_once(self, *, since=None):
        del since
        return self.processed

    def end_ops_run(self):
        self.run_keys.append(None)


def test_poll_job_records_degraded_terminal_run(monkeypatch):
    monkeypatch.setenv("PIPELINE_OPS_TRIGGER_SOURCE", "test")
    service = ResearchParserService.__new__(ResearchParserService)
    service._running = True
    service._since = None
    service.ops = FakeOps()
    service.pipeline = FakePipeline(failed=1)

    service._poll_job()

    assert service.ops.finished == [
        (
            "parser:test-run",
            {
                "status": "degraded",
                "stats": {"processed_count": 2, "failed_count": 1},
                "exit_code": 1,
            },
        )
    ]
    assert service.pipeline.run_keys == ["parser:test-run", None]
    assert service.ops.flush_count == 1
