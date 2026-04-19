from research_analysis_layer.evals.trigger import CaptureRequest


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
