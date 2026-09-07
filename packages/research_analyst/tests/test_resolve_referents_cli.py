from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.main import command_resolve_referents


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        analysis_db_url=f"sqlite:///{tmp_path / 'analysis.db'}",
        parsed_db_url="https://example.supabase.co",
        parsed_db_key="secret",
        calendar_db_url="https://example.supabase.co",
        calendar_db_key="secret",
        calendar_match_source="economic_events",
        calendar_source_name="economic_events",
        state_db_path=tmp_path / "state.db",
        batch_size=25,
        cron_mode_enabled=True,
        analysis_version="argmap-v1",
        chunker_version="deterministic-theme-v1",
        assertion_extractor_version="deterministic-theme-v1",
        resolver_version="bootstrap-v1",
        request_timeout_seconds=30,
        min_full_text_chars=500,
        min_quality_score=0.6,
        min_usable_theme_ratio=0.6,
        backfill_require_warning_free=True,
    )


def test_resolve_referents_apply_writes_keys(tmp_path):
    settings = _settings(tmp_path)
    store = AnalysisStore(settings.analysis_db_path)
    payload = {
        "argument_map": [
            {
                "claim": "Warsh speech was hawkish",
                "evidence": [
                    {
                        "text": "Chair Warsh's Jackson Hole speech was more hawkish than expected.",
                        "kind": "quote",
                        "referent_key": None,
                    }
                ],
            }
        ]
    }
    store.write_document_analysis(
        document_key="file:1",
        research_id=1,
        document_hash="hash-1",
        analysis_version="argmap-v1",
        run_id="9",
        payload_json=json.dumps(payload),
        thesis="thesis",
        confidence=0.8,
        total_input_tokens=1,
        total_output_tokens=1,
        total_tool_calls=0,
        total_duration_ms=10,
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = command_resolve_referents(
            settings,
            golden=str(
                Path(__file__).resolve().parents[1]
                / "evals"
                / "golden"
                / "referents.jsonl"
            ),
            apply=True,
            limit=None,
            granularity="coarse",
        )
    assert code == 0
    report = json.loads(buffer.getvalue())
    assert report["updated_rows"] == 1
    assert report["store_after"]["stored_resolved_count"] == 1

    rewritten = store.list_document_analyses()[0]["payload_json"]
    assert (
        rewritten["argument_map"][0]["evidence"][0]["referent_key"]
        == "event:jackson_hole_2026"
    )
