from datetime import datetime, timedelta
from pathlib import Path
from types import MethodType, SimpleNamespace

from src.parser.backend import BlockType, ConfidenceResult, TextBlock, TextParseResult
from src.parser.routing import ParsedDocument
from src.pipeline import Pipeline, build_source_document
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

    def insert_research(self, source, document_name: str, **kwargs):
        self.calls.append((source, document_name, kwargs))
        return {"document_name": document_name, "id": 1, "document_hash": "hash"}


def _build_pipeline(tmp_path, state: StateStore) -> Pipeline:
    pipeline = Pipeline.__new__(Pipeline)
    pipeline.settings = SimpleNamespace(
        artifact_base_dir=tmp_path / "artifacts",
        poll_interval_minutes=5,
        stale_processing_timeout_minutes=30,
        docling_ocr_retry=True,
    )
    pipeline.state = state
    pipeline.drive = _FailingDrive()
    pipeline.docling_backend = _FailingBackend()
    pipeline.docling_ocr_backend = None
    pipeline.mineru_backend = None
    pipeline.supabase = _SupabaseRecorder()
    return pipeline


def test_build_source_document_uses_filename_identity():
    source = build_source_document(
        "drive-1",
        "2026-08-31_GS_Rates_Report.pdf",
        "body",
    )
    assert source.source == "Goldman Sachs"
    assert source.source_date == "2026-08-31"
    assert source.document_id == "drive-1"
    assert source.document_uri == "gdrive://drive-1"


def test_process_file_resumes_from_artifacts(tmp_path):
    file_id = "file-source-only"
    file_name = "2026-08-31_GS_Rates_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.update_step(file_id, "parse", True)
    state.update_step(file_id, "boilerplate", True, ProcessingStatus.PARSING)

    artifact_dir = pipeline.settings.artifact_base_dir / file_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "clean_text.md").write_text(
        "# Rates Outlook\n\nDuration should rally if payrolls cool.\n",
        encoding="utf-8",
    )
    (artifact_dir / "blocks.jsonl").write_text(
        "\n".join(
            [
                '{"block_type":"heading","text":"Rates Outlook","page":1,'
                '"level":1,"bbox":null}',
                '{"block_type":"paragraph","text":"Duration should rally if payrolls cool.",'
                '"page":1,"level":null,"bbox":null}',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (artifact_dir / "parse.json").write_text(
        '{"backend":"docling","confidence_score":0.9,"confidence_status":"PASS","reasons":[]}\n',
        encoding="utf-8",
    )

    assert pipeline.process_file(file_id, file_name) is True
    assert len(pipeline.supabase.calls) == 1

    stored, stored_name, stored_kwargs = pipeline.supabase.calls[0]
    assert stored_name == file_name
    assert stored.source == "Goldman Sachs"
    assert stored.source_date == "2026-08-31"
    assert stored.full_text.startswith("# Rates Outlook")
    assert stored_kwargs["artifact_context"].parse_backend == "docling"
    assert stored_kwargs["artifact_context"].blocks
    assert stored_kwargs["artifact_context"].blocks[0].text == "Rates Outlook"

    final_state = state.get_state(file_id)
    assert final_state is not None
    assert final_state.status == ProcessingStatus.COMPLETED


def test_run_once_retries_old_partial_rows_before_new_files(tmp_path):
    file_id = "partial-123"
    file_name = "2026-03-14_Partial_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.mark_partial(file_id, "storage failed: old error")

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


def test_process_file_force_reparses_instead_of_resuming(tmp_path, monkeypatch):
    file_id = "file-source-only"
    file_name = "2026-08-31_GS_Rates_Report.pdf"
    state = StateStore(tmp_path / "state.db")
    pipeline = _build_pipeline(tmp_path, state)

    state.start_processing(file_id, file_name)
    state.update_step(file_id, "parse", True)
    state.update_step(file_id, "boilerplate", True)
    state.mark_completed(file_id)

    artifact_dir = pipeline.settings.artifact_base_dir / file_id
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "clean_text.md").write_text("OLD CLEAN TEXT\n", encoding="utf-8")
    (artifact_dir / "document.md").write_text("OLD DOCUMENT\n", encoding="utf-8")
    (artifact_dir / "blocks.jsonl").write_text(
        '{"block_type":"paragraph","text":"OLD CLEAN TEXT","page":1,"level":null,"bbox":null}\n',
        encoding="utf-8",
    )
    (artifact_dir / "parse.json").write_text(
        '{"backend":"docling","confidence_score":0.7,"confidence_status":"REPAIR","reasons":[]}\n',
        encoding="utf-8",
    )

    downloaded = []

    class _RecordingDrive:
        def download_file(self, got_id: str, got_name: str) -> Path:
            downloaded.append((got_id, got_name))
            path = tmp_path / got_name
            path.write_bytes(b"%PDF-1.4")
            return path

        def list_pdfs(self, days_ago=None, since=None):
            return []

    pipeline.drive = _RecordingDrive()

    def fake_parse(**_kwargs):
        blocks = [
            TextBlock(block_type=BlockType.PARAGRAPH, text="NEW BODY FROM OCR", page=1),
        ]
        return ParsedDocument(
            backend_name="docling-ocr",
            text_result=TextParseResult(blocks=blocks, raw_output="NEW BODY FROM OCR"),
            figures=[],
            confidence=ConfidenceResult(score=0.9, status="PASS", reasons=[]),
            ocr_retried=True,
            ocr_retry_reasons=["missing_pages"],
        )

    monkeypatch.setattr("src.pipeline.parse_with_optional_ocr", fake_parse)

    assert pipeline.process_file(file_id, file_name, force=True) is True
    assert downloaded == [(file_id, file_name)]

    clean_text = (artifact_dir / "clean_text.md").read_text(encoding="utf-8")
    assert "NEW BODY FROM OCR" in clean_text
    assert "OLD CLEAN TEXT" not in clean_text
    assert "NEW BODY FROM OCR" in (artifact_dir / "document.md").read_text(encoding="utf-8")

    stored, _stored_name, stored_kwargs = pipeline.supabase.calls[0]
    assert "NEW BODY FROM OCR" in stored.full_text
    assert stored_kwargs["artifact_context"].parse_backend == "docling-ocr"
    assert stored_kwargs["artifact_context"].ocr_retried is True

