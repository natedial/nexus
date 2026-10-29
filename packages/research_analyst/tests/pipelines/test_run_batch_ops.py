from datetime import UTC, datetime

from research_analysis_layer.models import ParserStateRecord
from research_analysis_layer.pipelines.run_batch import RunBatchPipeline


class FakeOps:
    def __init__(self):
        self.events = []

    def emit_stage_event(self, **kwargs):
        self.events.append(kwargs)


def test_document_event_uses_shared_identity_and_parent_run():
    pipeline = RunBatchPipeline.__new__(RunBatchPipeline)
    pipeline.ops_client = FakeOps()
    pipeline.ops_run_key = "analyst:test-run"
    state_row = ParserStateRecord(
        file_id="drive-1",
        file_name="research.pdf",
        status="completed",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    pipeline._emit_document_event(
        state_row,
        status="succeeded",
        research_id=42,
        document_hash="abc123",
        payload={"assertion_count": 3},
    )

    event = pipeline.ops_client.events[0]
    assert event["stage_name"] == "analyst.complete"
    assert event["run_key"] == "analyst:test-run"
    assert event["document_key"] == "file:drive-1"
    assert event["research_id"] == 42
    assert event["payload"] == {"assertion_count": 3}
