import json
from datetime import datetime, timedelta
from types import MethodType, SimpleNamespace

from src.extraction.models import Excerpt, Metadata, Theme, Trade
from src.pipeline import Pipeline, _is_reusable_metadata
from src.storage.state import ProcessingStatus, StateStore


class _FailingDrive:
    def download_file(self, file_id: str, file_name: str):
        raise AssertionError("download_file should not be called when artifacts exist")

    def list_pdfs(self, days_ago=None, since=None):
        return []


class _FailingBackend:
    def parse_text(self, file_path):
        raise AssertionError("parse_text should not be called when artifacts exist")

    def extract_figures(self, file_path):
        raise AssertionError("extract_figures should not be called when artifacts exist")


class _SupabaseRecorder:
    def __init__(self):
        self.calls = []

    def insert_research(self, result, document_name: str):
        self.calls.append((result, document_name))
        return {"document_name": document_name}


def _build_pipeline(tmp_path, state: StateStore) -> Pipeline:
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.settings = SimpleNamespace(
        artifact_base_dir=tmp_path / "artifacts",
        boilerplate_deterministic_only=False,
        poll_interval_minutes=5,
        stale_processing_timeout_minutes=30,
    )
    pipeline.state = state
    pipeline.drive = _FailingDrive()
    pipeline.docling_backend = _FailingBackend()
    pipeline.llama_backend = _FailingBackend()
    pipeline.mineru_backend = None
    pipeline.llm = object()
    pipeline.model_config = SimpleNamespace(
        metadata=object(),
        themes=object(),
        trades=object(),
        boilerplate=object(),
    )
    pipeline.supabase = _SupabaseRecorder()
    return pipeline


def test_process_file_resumes_from_artifacts_and_skips_completed_steps(tmp_path, monkeypatch):
    file_id = "file-123"
    file_name = "2026-03-15_Test_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.update_step(file_id, "parse", True)
    state.update_step(file_id, "boilerplate", True, ProcessingStatus.EXTRACTING)
    state.update_step(file_id, "metadata", True)
    state.update_step(file_id, "themes", False, error_message="Themes failed: old error")
    state.update_step(file_id, "trades", False, error_message="Trades failed: old error")
    state.mark_partial(file_id, "themes: old error; trades: old error")

    artifact_dir = pipeline.settings.artifact_base_dir / file_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "clean_text.md").write_text("clean text\n", encoding="utf-8")
    (artifact_dir / "extraction.json").write_text(
        json.dumps(
            {
                "metadata_ok": True,
                "themes_ok": False,
                "trades_ok": False,
                "metadata": {
                    "source": "Morgan Stanley",
                    "source_date": "2026-03-15",
                    "area": "USD",
                    "region": "US",
                    "asset_focus": "rates",
                },
                "themes": None,
                "trades": None,
            }
        ),
        encoding="utf-8",
    )

    calls = {"metadata": 0, "themes": 0, "trades": 0}

    def _fake_extract_metadata(*args, **kwargs):
        calls["metadata"] += 1
        raise AssertionError("metadata should not be re-extracted")

    def _fake_extract_themes(*args, **kwargs):
        calls["themes"] += 1
        return [
            Theme(
                label="Curve steepening",
                excerpts=[Excerpt(text="Front-end pressure")],
                relevance=["Rates"],
            )
        ]

    def _fake_extract_trades(*args, **kwargs):
        calls["trades"] += 1
        return [Trade(text="Receive 2y swaps")]

    monkeypatch.setattr("src.pipeline.extract_metadata", _fake_extract_metadata)
    monkeypatch.setattr("src.pipeline.extract_themes", _fake_extract_themes)
    monkeypatch.setattr("src.pipeline.extract_trades", _fake_extract_trades)

    assert pipeline.process_file(file_id, file_name) is True

    assert calls == {"metadata": 0, "themes": 1, "trades": 1}
    assert len(pipeline.supabase.calls) == 1

    stored_result, stored_name = pipeline.supabase.calls[0]
    assert stored_name == file_name
    assert stored_result.metadata.source == "Morgan Stanley"
    assert len(stored_result.themes) == 1
    assert len(stored_result.trades) == 1

    final_state = state.get_state(file_id)
    assert final_state is not None
    assert final_state.status == ProcessingStatus.COMPLETED

    payload = json.loads((artifact_dir / "extraction.json").read_text(encoding="utf-8"))
    assert payload["metadata_ok"] is True
    assert payload["themes_ok"] is True
    assert payload["trades_ok"] is True


def test_process_file_reruns_stale_metadata_on_filename_source_mismatch(tmp_path, monkeypatch):
    file_id = "file-456"
    file_name = "2026-05-03_DB_Rates_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.update_step(file_id, "parse", True)
    state.update_step(file_id, "boilerplate", True, ProcessingStatus.EXTRACTING)
    state.update_step(file_id, "metadata", True)
    state.update_step(file_id, "themes", False, error_message="Themes failed: old error")
    state.update_step(file_id, "trades", True)
    state.mark_partial(file_id, "themes: old error")

    artifact_dir = pipeline.settings.artifact_base_dir / file_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "clean_text.md").write_text("clean text\n", encoding="utf-8")
    (artifact_dir / "extraction.json").write_text(
        json.dumps(
            {
                "metadata_ok": True,
                "themes_ok": False,
                "trades_ok": True,
                "metadata": {
                    "source": "Goldman Sachs",
                    "source_date": "2026-05-03",
                    "area": "USD",
                    "region": "US",
                    "asset_focus": "rates",
                },
                "themes": None,
                "trades": [{"text": "Receive 2y swaps"}],
            }
        ),
        encoding="utf-8",
    )

    calls = {"metadata": 0, "themes": 0, "trades": 0}

    def _fake_extract_metadata(*args, **kwargs):
        calls["metadata"] += 1
        return Metadata(
            source="Deutsche Bank",
            source_date="2026-05-03",
            area="USD",
            region="US",
            asset_focus="rates",
        )

    def _fake_extract_themes(*args, **kwargs):
        calls["themes"] += 1
        return [
            Theme(
                label="Balance sheet policy",
                excerpts=[Excerpt(text="QT effects differ from rates")],
                relevance=["Rates"],
            )
        ]

    def _fake_extract_trades(*args, **kwargs):
        calls["trades"] += 1
        raise AssertionError("trades should be reused")

    monkeypatch.setattr("src.pipeline.extract_metadata", _fake_extract_metadata)
    monkeypatch.setattr("src.pipeline.extract_themes", _fake_extract_themes)
    monkeypatch.setattr("src.pipeline.extract_trades", _fake_extract_trades)

    assert pipeline.process_file(file_id, file_name) is True

    assert calls == {"metadata": 1, "themes": 1, "trades": 0}
    stored_result, _ = pipeline.supabase.calls[0]
    assert stored_result.metadata.source == "Deutsche Bank"


def test_metadata_reuse_accepts_known_filename_source_alias():
    metadata = Metadata(source="J.P. Morgan")

    assert _is_reusable_metadata(metadata, "2026-05-03_JPM_Rates_Report.pdf")


def test_metadata_reuse_rejects_known_filename_source_mismatch():
    metadata = Metadata(source="Goldman Sachs")

    assert not _is_reusable_metadata(metadata, "2026-05-03_DB_Rates_Report.pdf")


def test_metadata_reuse_accepts_unknown_filename_prefix_as_ambiguous():
    metadata = Metadata(source="Goldman Sachs")

    assert _is_reusable_metadata(metadata, "2026-05-03_BOFA_Rates_Report.pdf")


def test_metadata_reuse_accepts_non_source_date_prefixed_filename_as_ambiguous():
    metadata = Metadata(source="Morgan Stanley")

    assert _is_reusable_metadata(metadata, "2026-05-03_US_Rates_Report.pdf")


def test_run_once_retries_old_partial_rows_before_new_files(tmp_path):
    file_id = "partial-123"
    file_name = "2026-03-14_Partial_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.mark_partial(file_id, "metadata failed: old error")

    stale_timestamp = (datetime.utcnow() - timedelta(minutes=10)).isoformat()
    with state._connect() as conn:
        conn.execute(
            "UPDATE processed_files SET updated_at = ? WHERE file_id = ?",
            (stale_timestamp, file_id),
        )
        conn.commit()

    retried = []

    def _fake_process_file(self, retry_file_id: str, retry_file_name: str) -> bool:
        retried.append((retry_file_id, retry_file_name))
        return True

    pipeline.process_file = MethodType(_fake_process_file, pipeline)

    assert pipeline.run_once() == 1
    assert retried == [(file_id, file_name)]
