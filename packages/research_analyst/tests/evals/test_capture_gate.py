from research_analysis_layer.services.capture_gate import (
    CaptureDecision,
    should_capture,
)


def _doc_analysis(*, confidence: float, thesis: str = "x"):
    return {"confidence": confidence, "thesis": thesis}


def _debate_session(*, accepted_count: int, contested_count: int):
    return {
        "verdicts": (
            [{"verdict_label": "accepted"} for _ in range(accepted_count)]
            + [{"verdict_label": "contested"} for _ in range(contested_count)]
        ),
    }


def test_capture_when_thesis_accepted_and_confidence_high():
    decision = should_capture(
        _doc_analysis(confidence=0.85),
        _debate_session(accepted_count=2, contested_count=0),
        min_confidence=0.75,
    )
    assert decision == CaptureDecision(capture=True, reason="ok")


def test_skip_when_no_accepted_arguments():
    decision = should_capture(
        _doc_analysis(confidence=0.85),
        _debate_session(accepted_count=0, contested_count=1),
        min_confidence=0.75,
    )
    assert decision.capture is False
    assert "accepted" in decision.reason


def test_skip_when_confidence_below_threshold():
    decision = should_capture(
        _doc_analysis(confidence=0.5),
        _debate_session(accepted_count=2, contested_count=0),
        min_confidence=0.75,
    )
    assert decision.capture is False
    assert "confidence" in decision.reason


def test_skip_when_thesis_missing():
    decision = should_capture(
        _doc_analysis(confidence=0.85, thesis=""),
        _debate_session(accepted_count=2, contested_count=0),
        min_confidence=0.75,
    )
    assert decision.capture is False
    assert "thesis" in decision.reason
