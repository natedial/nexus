from unittest.mock import MagicMock
import pytest

from research_analysis_layer.pipelines.analyze_document import AnalyzeDocumentPipeline


def _doc_analysis(thesis: str, confidence: float, run_id: int = 42):
    m = MagicMock()
    m.thesis = thesis
    m.confidence = confidence
    m.document_key = "doc:7:abc"
    m.research_id = 7
    m.document_hash = "abc"
    m.analysis_version = "v1"
    m.metadata.run_id = run_id
    m.metadata.model_used = "gpt-5-mini"
    m.round_traces = []
    m.model_dump.return_value = {"thesis": thesis, "confidence": confidence}
    m.model_dump_json.return_value = f'{{"thesis":"{thesis}"}}'
    return m


def _document():
    d = MagicMock()
    d.ready_for_analysis = True
    d.research_id = 7
    d.document_hash = "abc"
    d.file_id = None
    return d


def _stub_registry(monkeypatch):
    import research_analysis_layer.services.agent_registry as ar

    fake_registry = MagicMock()
    synth_round = MagicMock(
        name="synthesis",
        agents=["synthesizer"],
        output_schema="DocumentAnalysis",
        receives=["input"],
        receives_forum_state=True,
        writes_forum_state=False,
    )
    synth_round.name = "synthesis"
    fake_registry.get_rounds.return_value = [synth_round]
    fake_registry.get_agent_spec.return_value = MagicMock(name="synth-spec")
    monkeypatch.setattr(ar, "get_registry", lambda: fake_registry)
    return fake_registry, synth_round


def test_shadow_mode_writes_both_rows(monkeypatch):
    fake_registry, synth_round = _stub_registry(monkeypatch)

    debate_analysis = _doc_analysis("debate-thesis", 0.82)
    baseline_analysis = _doc_analysis("baseline-thesis", 0.78)

    round_executor = MagicMock()
    round_executor.debate_mode = "shadow"
    round_executor.rollout_stats = MagicMock(
        shadow_runs_total=0, shadow_failures_total=0, shadow_debate_truncated_total=0
    )
    round_executor.run.return_value = debate_analysis
    round_executor.run_baseline_synthesis.return_value = baseline_analysis

    store = MagicMock()
    store.load_debate_session.return_value = {"verdicts": []}

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
        eval_trigger=None,
    )
    pipeline.run(run_id=42, parser_updated_at=None, document=_document())

    store.write_shadow_document_analysis.assert_called_once()
    shadow_kwargs = store.write_shadow_document_analysis.call_args.kwargs
    assert shadow_kwargs["variant"] == "debate"
    assert shadow_kwargs["thesis"] == "debate-thesis"
    store.write_document_analysis.assert_called_once()
    auth_kwargs = store.write_document_analysis.call_args.kwargs
    assert auth_kwargs["thesis"] == "baseline-thesis"


def test_shadow_mode_debate_failure_still_writes_baseline(monkeypatch):
    fake_registry, synth_round = _stub_registry(monkeypatch)
    baseline_analysis = _doc_analysis("baseline-only", 0.7)

    round_executor = MagicMock()
    round_executor.debate_mode = "shadow"
    stats = MagicMock(shadow_runs_total=0, shadow_failures_total=0)
    round_executor.rollout_stats = stats
    round_executor.run.return_value = None  # debate chain fails
    round_executor.run_baseline_synthesis.return_value = baseline_analysis

    store = MagicMock()
    store.load_debate_session.return_value = None

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
        eval_trigger=None,
    )
    pipeline.run(run_id=42, parser_updated_at=None, document=_document())

    store.write_shadow_document_analysis.assert_not_called()
    store.write_document_analysis.assert_called_once()
    assert stats.shadow_failures_total == 1


def test_shadow_mode_run_exception_falls_back_to_baseline(monkeypatch):
    fake_registry, synth_round = _stub_registry(monkeypatch)
    baseline_analysis = _doc_analysis("baseline-fallback", 0.7)

    round_executor = MagicMock()
    round_executor.debate_mode = "shadow"
    stats = MagicMock(shadow_runs_total=0, shadow_failures_total=0)
    round_executor.rollout_stats = stats
    round_executor.run.side_effect = RuntimeError("debate exploded")
    round_executor.run_baseline_synthesis.return_value = baseline_analysis

    store = MagicMock()
    store.load_debate_session.return_value = None

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
        eval_trigger=None,
    )
    pipeline.run(run_id=42, parser_updated_at=None, document=_document())

    store.write_document_analysis.assert_called_once()
    auth_kwargs = store.write_document_analysis.call_args.kwargs
    assert auth_kwargs["thesis"] == "baseline-fallback"
    assert stats.shadow_failures_total == 1
    store.write_shadow_document_analysis.assert_not_called()


def test_on_mode_unchanged(monkeypatch):
    fake_registry, synth_round = _stub_registry(monkeypatch)
    debate_analysis = _doc_analysis("debate-only", 0.85)
    round_executor = MagicMock()
    round_executor.debate_mode = "on"
    round_executor.rollout_stats = MagicMock()
    round_executor.run.return_value = debate_analysis

    store = MagicMock()
    store.load_debate_session.return_value = {"verdicts": []}

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
        eval_trigger=None,
    )
    pipeline.run(run_id=42, parser_updated_at=None, document=_document())

    store.write_shadow_document_analysis.assert_not_called()
    round_executor.run_baseline_synthesis.assert_not_called()
    store.write_document_analysis.assert_called_once()
