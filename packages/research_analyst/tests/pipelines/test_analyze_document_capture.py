from unittest.mock import MagicMock

from research_analysis_layer.evals.trigger import CaptureRequest


def test_pipeline_fires_capture_request_with_synthesizer_input(monkeypatch):
    """End-to-end shape test: assert the pipeline assembles the right CaptureRequest."""
    from research_analysis_layer.pipelines.analyze_document import (
        AnalyzeDocumentPipeline,
    )

    captured: list[CaptureRequest] = []
    trigger = MagicMock()
    trigger.fire.side_effect = lambda req: (captured.append(req), True)[1]

    fake_doc_analysis = MagicMock()
    fake_doc_analysis.confidence = 0.85
    fake_doc_analysis.thesis = "Long EUR rates"
    fake_doc_analysis.document_key = "doc:7:abc"
    fake_doc_analysis.research_id = 7
    fake_doc_analysis.document_hash = "abc"
    fake_doc_analysis.analysis_version = "v1"
    fake_doc_analysis.metadata.run_id = 42
    fake_doc_analysis.metadata.model_used = "gpt-5-mini"
    fake_doc_analysis.model_dump.return_value = {
        "thesis": "Long EUR rates",
        "confidence": 0.85,
    }
    fake_doc_analysis.model_dump_json.return_value = '{"thesis":"Long EUR rates"}'
    fake_doc_analysis.round_traces = []

    store = MagicMock()
    store.load_debate_session.return_value = {
        "verdicts": [{"verdict_label": "accepted"}],
    }

    round_executor = MagicMock()
    round_executor.run.return_value = fake_doc_analysis

    # Stub out the agent registry so pipeline doesn't try to load real config.
    import research_analysis_layer.services.agent_registry as agent_registry

    fake_registry = MagicMock()
    fake_registry.get_rounds.return_value = []
    monkeypatch.setattr(agent_registry, "get_registry", lambda: fake_registry)

    # Stub AgentInputBuilder so the captured synthesizer_input shape is predictable.
    import research_analysis_layer.services.agent_input_builder as aib_mod

    class _FakeBuilder:
        def build(self, **kwargs):
            return {"agent_type": kwargs["agent_type"], "document": {"research_id": 7}}

    monkeypatch.setattr(aib_mod, "AgentInputBuilder", _FakeBuilder)

    pipeline = AnalyzeDocumentPipeline(
        store=store,
        chunker=MagicMock(chunk_document=MagicMock(return_value=[])),
        evidence_builder=MagicMock(build_evidence=MagicMock(return_value=[])),
        assertion_extractor=MagicMock(extract=MagicMock(return_value=[])),
        resolver=MagicMock(
            resolve_nodes=MagicMock(return_value=[]),
            resolve_edges=MagicMock(return_value=[]),
        ),
        graph_updater=MagicMock(),
        lifecycle_service=MagicMock(),
        quality_reviewer=MagicMock(
            review=MagicMock(
                return_value=MagicMock(passed=True, score=0.9, blocking_issues=[])
            ),
            to_json=MagicMock(return_value="{}"),
        ),
        analysis_version="v1",
        round_executor=round_executor,
        eval_trigger=trigger,
    )

    document = MagicMock()
    document.ready_for_analysis = True
    document.research_id = 7
    document.document_hash = "abc"
    document.file_id = None

    pipeline.run(run_id=42, parser_updated_at=None, document=document)

    assert len(captured) == 1
    req = captured[0]
    assert req.document_id == "abc"
    assert req.analysis_version == "v1"
    assert req.agent_type == "synthesizer"
    assert req.confidence == 0.85
    assert req.metadata["debate_session_id"].startswith("debate:7:abc:v1:42")
    assert req.metadata["model_used"] == "gpt-5-mini"
    assert req.metadata["schema_valid"] is True
    assert req.quality_signals.get("forum_accepted_count") == 1
    assert "document" in req.input_payload
