import threading
from unittest.mock import MagicMock

from research_analysis_layer.evals.trigger import CaptureRequest, EvalTrigger


def test_capture_request_holds_input_output_and_metadata():
    req = CaptureRequest(
        document_id="docabc",
        analysis_version="bootstrap-v1",
        agent_type="synthesizer",
        input_payload={"agent_type": "synthesizer", "document": {"research_id": 7}},
        output_payload={"thesis": "x", "confidence": 0.82},
        metadata={
            "model_used": "gpt-5-mini",
            "run_id": 42,
            "debate_session_id": "debate:7:hash:bootstrap-v1:42",
            "schema_valid": True,
        },
        confidence=0.82,
        quality_signals={"forum_accepted_thesis": True},
    )
    assert req.dedupe_key == "docabc:bootstrap-v1"
    assert req.metadata["debate_session_id"].startswith("debate:")


def _request(idx: int) -> CaptureRequest:
    return CaptureRequest(
        document_id=f"doc{idx}",
        analysis_version="v1",
        agent_type="synthesizer",
        input_payload={},
        output_payload={},
        metadata={},
        confidence=1.0,
    )


def test_eval_trigger_drops_when_queue_full_and_counts_drops():
    manager = MagicMock()
    blocking_event = threading.Event()

    def slow_capture(_request):
        blocking_event.wait(timeout=2)

    manager.capture_request.side_effect = slow_capture

    trigger = EvalTrigger(manager, max_queue_size=2)
    try:
        assert trigger.fire(_request(1)) is True
        assert trigger.fire(_request(2)) is True
        assert trigger.fire(_request(3)) is True
        accepted = sum(trigger.fire(_request(i)) for i in range(4, 8))
        assert trigger.dropped_count >= 1
        assert accepted < 4
    finally:
        blocking_event.set()
        trigger.shutdown(wait=True)
