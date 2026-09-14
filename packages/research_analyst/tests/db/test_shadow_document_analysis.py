from pathlib import Path
from research_analysis_layer.db.analysis_store import AnalysisStore


def _store(tmp_path: Path) -> AnalysisStore:
    return AnalysisStore(tmp_path / "analysis.db")


def test_write_and_load_shadow_document_analysis(tmp_path):
    store = _store(tmp_path)
    store.write_shadow_document_analysis(
        research_id=7,
        document_hash="abc",
        analysis_version="v1",
        run_id="42",
        variant="debate",
        payload_json='{"thesis":"x"}',
        thesis="x",
        confidence=0.82,
        total_input_tokens=100,
        total_output_tokens=50,
        total_duration_ms=1234,
        debate_session_id="debate:7:abc:v1:42",
    )
    row = store.load_shadow_document_analysis(
        research_id=7,
        document_hash="abc",
        analysis_version="v1",
        run_id="42",
        variant="debate",
    )
    assert row is not None
    assert row["thesis"] == "x"
    assert row["confidence"] == 0.82
    assert row["debate_session_id"] == "debate:7:abc:v1:42"


def test_shadow_document_analysis_primary_key_allows_variants(tmp_path):
    store = _store(tmp_path)
    common = dict(
        research_id=7,
        document_hash="abc",
        analysis_version="v1",
        run_id="42",
        payload_json="{}",
        thesis="",
        confidence=0.0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_duration_ms=0,
        debate_session_id=None,
    )
    store.write_shadow_document_analysis(variant="debate", **common)
    store.write_shadow_document_analysis(variant="inverse", **common)
    assert (
        store.load_shadow_document_analysis(
            research_id=7,
            document_hash="abc",
            analysis_version="v1",
            run_id="42",
            variant="debate",
        )
        is not None
    )
    assert (
        store.load_shadow_document_analysis(
            research_id=7,
            document_hash="abc",
            analysis_version="v1",
            run_id="42",
            variant="inverse",
        )
        is not None
    )


def test_load_shadow_document_analysis_missing_returns_none(tmp_path):
    store = _store(tmp_path)
    assert (
        store.load_shadow_document_analysis(
            research_id=1,
            document_hash="none",
            analysis_version="v1",
            run_id="1",
            variant="debate",
        )
        is None
    )
