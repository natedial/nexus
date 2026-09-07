from __future__ import annotations

from unittest.mock import MagicMock

from research_analysis_layer.models import (
    DocumentQualityReport,
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
)
from research_analysis_layer.pipelines.analyze_document import AnalyzeDocumentPipeline


def _make_document() -> HydratedParsedDocument:
    document = ParsedDocument(
        id=5246,
        document_name="2026-04-15_Test.pdf",
        source="Test",
        source_date="2026-04-15",
        parsed_data={"full_text": "Macro outlook " * 50, "metadata": {}},
        theme_count=1,
        trade_count=0,
        document_hash="hash-5246",
    )
    theme = ParsedTheme(
        id=1,
        research_id=5246,
        theme_order=1,
        label="Test theme",
        scope=None,
        primary_category="Macro",
        relevance=["Macro"],
        classification="Forecast",
        strength="Primary",
        confidence="High",
        evidence_count=1,
        mention_count=1,
        context="Policy remains restrictive.",
        directionality=None,
        argument_structure=None,
    )
    excerpt = ParsedExcerpt(
        id=1,
        theme_id=1,
        excerpt_order=1,
        excerpt_text="Policy remains restrictive.",
    )
    return HydratedParsedDocument(
        document=document,
        themes=[HydratedTheme(theme=theme, excerpts=[excerpt])],
        file_id="file-5246",
    )


def test_pipeline_errors_when_synthesizer_produces_no_document_analysis():
    store = MagicMock()
    chunker = MagicMock()
    chunker.chunk_document.return_value = []
    evidence_builder = MagicMock()
    evidence_builder.build_evidence.return_value = []
    assertion_extractor = MagicMock()
    resolver = MagicMock()
    graph_updater = MagicMock()
    lifecycle_service = MagicMock()
    quality_reviewer = MagicMock()
    quality_report = DocumentQualityReport(score=0.95)
    quality_reviewer.review.return_value = quality_report
    quality_reviewer.to_json.return_value = '{"score": 0.95}'
    round_executor = MagicMock()
    round_executor.run.return_value = None

    pipeline = AnalyzeDocumentPipeline(
        store=store,
        chunker=chunker,
        evidence_builder=evidence_builder,
        assertion_extractor=assertion_extractor,
        resolver=resolver,
        graph_updater=graph_updater,
        lifecycle_service=lifecycle_service,
        quality_reviewer=quality_reviewer,
        analysis_version="bootstrap-v1",
        round_executor=round_executor,
    )

    result = pipeline.run(
        run_id=99,
        parser_updated_at="2026-04-16T00:00:00+00:00",
        document=_make_document(),
        agent_only=True,
    )

    assert result.status == "error"
    assert result.error_type == "agent_no_output"
    assert result.agent_no_output_count == 1
    store.write_document_analysis.assert_not_called()


def test_pipeline_succeeds_and_writes_document_analysis():
    from research_analysis_layer.models.agent_outputs import (
        DocumentAnalysis,
        RoundTrace,
        AgentExecutionMetadata,
    )
    from datetime import datetime, timezone

    store = MagicMock()
    chunker = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.chunk_order = 0
    chunker.chunk_document.return_value = [mock_chunk]

    evidence_builder = MagicMock()
    evidence_builder.build_evidence.return_value = []

    mock_assertion = MagicMock()
    mock_assertion.chunk_order = 0
    assertion_extractor = MagicMock()
    assertion_extractor.extract.return_value = [mock_assertion]

    resolver = MagicMock()
    resolver.resolve_nodes.return_value = []
    resolver.resolve_edges.return_value = []

    graph_updater = MagicMock()
    graph_updater.apply_resolutions.return_value = MagicMock(
        node_upsert_count=0, edge_upsert_count=0, open_question_count=0
    )

    lifecycle_service = MagicMock()

    quality_reviewer = MagicMock()
    quality_report = DocumentQualityReport(score=0.95, blocking_issues=[])
    quality_reviewer.review.return_value = quality_report
    quality_reviewer.to_json.return_value = '{"score": 0.95, "passed": true}'

    doc_analysis = DocumentAnalysis(
        document_key="file:file-5246",
        research_id=5246,
        document_hash="hash-5246",
        analysis_version="bootstrap-v1",
        thesis="Test thesis",
        contrarian_view="Test contrarian",
        recommended_positioning="Test positioning",
        trading_opportunities=[],
        short_time_horizon_insights=[],
        talking_points=[],
        cross_document_references=[],
        round_traces=[
            RoundTrace(
                round_name="synthesis",
                duration_ms=100,
                agent_count=1,
                failed_agent_count=0,
                tool_call_count=0,
                input_tokens=100,
                output_tokens=50,
            )
        ],
        confidence=0.8,
        metadata=AgentExecutionMetadata(
            research_id=5246,
            document_hash="hash-5246",
            analysis_version="bootstrap-v1",
            agent_type="synthesizer",
            model_requested="gpt-5-mini",
            model_used="gpt-5-mini",
            prompt_path="prompts/agents/synthesizer.txt",
            prompt_version="abc123",
            run_id=99,
            attempt_count=1,
            analyzed_at=datetime.now(timezone.utc),
        ),
        quality={},
        themes=[],
        trades=[],
        assertions=[],
        world_nodes=[],
        world_edges=[],
        forecast_candidates=[],
    )

    round_executor = MagicMock()
    round_executor.run.return_value = doc_analysis

    pipeline = AnalyzeDocumentPipeline(
        store=store,
        chunker=chunker,
        evidence_builder=evidence_builder,
        assertion_extractor=assertion_extractor,
        resolver=resolver,
        graph_updater=graph_updater,
        lifecycle_service=lifecycle_service,
        quality_reviewer=quality_reviewer,
        analysis_version="bootstrap-v1",
        round_executor=round_executor,
    )

    result = pipeline.run(
        run_id=99,
        parser_updated_at="2026-04-16T00:00:00+00:00",
        document=_make_document(),
    )

    assert result.status == "success"
    store.write_document_analysis.assert_called_once()
    call_kwargs = store.write_document_analysis.call_args[1]
    assert call_kwargs["thesis"] == "Test thesis"
    assert call_kwargs["research_id"] == 5246
    assert call_kwargs["document_hash"] == "hash-5246"
    assert call_kwargs["analysis_version"] == "bootstrap-v1"
    assert call_kwargs["total_input_tokens"] == 100
    assert call_kwargs["total_output_tokens"] == 50
    assert call_kwargs["total_tool_calls"] == 0


def test_pipeline_resolves_referent_keys_before_write():
    import json
    from datetime import datetime, timezone

    from research_analysis_layer.models.agent_outputs import (
        AgentExecutionMetadata,
        ClaimNode,
        DocumentAnalysis,
        EvidenceRef,
        RoundTrace,
    )
    from research_analysis_layer.services.evidence_referent_resolver import (
        EvidenceReferentResolver,
    )

    store = MagicMock()
    chunker = MagicMock()
    chunker.chunk_document.return_value = []
    evidence_builder = MagicMock()
    evidence_builder.build_evidence.return_value = []
    assertion_extractor = MagicMock()
    quality_reviewer = MagicMock()
    quality_report = DocumentQualityReport(score=0.95, blocking_issues=[])
    quality_reviewer.review.return_value = quality_report
    quality_reviewer.to_json.return_value = '{"score": 0.95, "passed": true}'

    doc_analysis = DocumentAnalysis(
        document_key="file:file-5246",
        research_id=5246,
        document_hash="hash-5246",
        analysis_version="bootstrap-v1",
        thesis="Test thesis",
        contrarian_view="Test contrarian",
        recommended_positioning="Test positioning",
        trading_opportunities=[],
        short_time_horizon_insights=[],
        talking_points=[],
        cross_document_references=[],
        round_traces=[
            RoundTrace(
                round_name="synthesis",
                duration_ms=100,
                agent_count=1,
                failed_agent_count=0,
                tool_call_count=0,
                input_tokens=100,
                output_tokens=50,
            )
        ],
        confidence=0.8,
        metadata=AgentExecutionMetadata(
            research_id=5246,
            document_hash="hash-5246",
            analysis_version="bootstrap-v1",
            agent_type="synthesizer",
            model_requested="gpt-5-mini",
            model_used="gpt-5-mini",
            prompt_path="prompts/agents/synthesizer.txt",
            prompt_version="abc123",
            run_id=99,
            attempt_count=1,
            analyzed_at=datetime.now(timezone.utc),
        ),
        argument_map=[
            ClaimNode(
                claim="Warsh's Jackson Hole speech was hawkish.",
                evidence=[
                    EvidenceRef(
                        text="Chair Warsh's Jackson Hole speech was more hawkish than expected.",
                        kind="quote",
                    )
                ],
            )
        ],
    )
    round_executor = MagicMock()
    round_executor.run.return_value = doc_analysis

    pipeline = AnalyzeDocumentPipeline(
        store=store,
        chunker=chunker,
        evidence_builder=evidence_builder,
        assertion_extractor=assertion_extractor,
        resolver=MagicMock(resolve_nodes=MagicMock(return_value=[]), resolve_edges=MagicMock(return_value=[])),
        graph_updater=MagicMock(),
        lifecycle_service=MagicMock(),
        quality_reviewer=quality_reviewer,
        analysis_version="bootstrap-v1",
        round_executor=round_executor,
        referent_resolver=EvidenceReferentResolver(granularity="coarse"),
    )

    result = pipeline.run(
        run_id=99,
        parser_updated_at="2026-04-16T00:00:00+00:00",
        document=_make_document(),
        agent_only=True,
    )

    assert result.status == "success"
    payload = json.loads(store.write_document_analysis.call_args[1]["payload_json"])
    assert (
        payload["argument_map"][0]["evidence"][0]["referent_key"]
        == "event:jackson_hole_2026"
    )
