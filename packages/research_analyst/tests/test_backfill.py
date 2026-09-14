from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import (
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
    RunItemResult,
)
from research_analysis_layer.pipelines.run_batch import RunBatchPipeline
from research_analysis_layer.services import QualityReviewer, Selector


def make_settings(db_path: Path) -> Settings:
    return Settings(
        analysis_db_url=f"sqlite:///{db_path}",
        parsed_db_url="https://example.supabase.co",
        parsed_db_key="secret",
        calendar_db_url="https://calendar.example.supabase.co",
        calendar_db_key="calendar-secret",
        calendar_match_source="economic_events",
        calendar_source_name="economic_events",
        state_db_path=Path("data/state.db"),
        batch_size=25,
        cron_mode_enabled=True,
        analysis_version="bootstrap-v1",
        chunker_version="deterministic-theme-v1",
        assertion_extractor_version="deterministic-theme-v1",
        resolver_version="bootstrap-v1",
        request_timeout_seconds=30,
        min_full_text_chars=500,
        min_quality_score=0.6,
        min_usable_theme_ratio=0.6,
        backfill_require_warning_free=True,
    )


def make_warning_document() -> HydratedParsedDocument:
    parsed_data = {
        "full_text": "Macro outlook " * 200,
        "metadata": {"document_id": "file-1"},
    }
    document = ParsedDocument(
        id=1,
        document_name="2026-03-30_JPM_macro_outlook.pdf",
        source="J.P. Morgan",
        source_date="2026-03-30",
        parsed_data=parsed_data,
        theme_count=2,
        document_hash="hash123",
    )
    themes = [
        ParsedTheme(
            id=10,
            research_id=1,
            theme_order=1,
            label="Delayed cuts",
            scope=None,
            primary_category="Rates",
            relevance=["Rates"],
            classification="Forecast",
            strength="Primary",
            confidence="High",
            evidence_count=2,
            mention_count=1,
            context="Cuts are less likely in June.",
            directionality=None,
            argument_structure=None,
        ),
        ParsedTheme(
            id=11,
            research_id=1,
            theme_order=2,
            label="Higher term premium",
            scope=None,
            primary_category="Macro",
            relevance=["Macro"],
            classification="Description",
            strength="Primary",
            confidence="High",
            evidence_count=2,
            mention_count=1,
            context="Supply pressure keeps term premium elevated.",
            directionality=None,
            argument_structure=None,
        ),
    ]
    excerpts = [
        [ParsedExcerpt(id=101, theme_id=10, excerpt_order=1, excerpt_text="A" * 120)],
        [ParsedExcerpt(id=102, theme_id=11, excerpt_order=1, excerpt_text="B" * 120)],
    ]
    hydrated_themes = [
        HydratedTheme(theme=theme, excerpts=theme_excerpts)
        for theme, theme_excerpts in zip(themes, excerpts)
    ]
    return HydratedParsedDocument(
        document=document,
        themes=hydrated_themes,
        file_id="file-1",
    )


class FakeParsedDbClient:
    def __init__(self, documents: list[HydratedParsedDocument]) -> None:
        self.documents = documents

    def hydrate_search(self, **kwargs) -> list[HydratedParsedDocument]:
        del kwargs
        return list(self.documents)


class FakeCalendarDbClient:
    def check_connection(self):
        return True, "ok"


class FakeHydrator:
    def __init__(self, documents: list[HydratedParsedDocument]) -> None:
        self.documents_by_file_id = {document.file_id: document for document in documents}

    def hydrate_from_state(self, state_row):
        return self.documents_by_file_id.get(state_row.file_id)


class FakeAnalyzeDocument:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(
        self,
        run_id: int,
        parser_updated_at,
        document: HydratedParsedDocument,
        **kwargs,
    ) -> RunItemResult:
        del run_id
        del parser_updated_at
        del kwargs
        self.calls.append(document.file_id)
        return RunItemResult(
            status="success",
            quality_score=1.0,
            quality_summary_json="{}",
        )


class _NoOpContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False


class FakeOps:
    def flush(self) -> None:
        return None

    def start_run(self, **kwargs) -> str:
        del kwargs
        return "ops-run"

    def emit_stage_event(self, **kwargs) -> None:
        del kwargs
        return None

    def track_stage(self, **kwargs):
        del kwargs
        return _NoOpContext()

    def update_run(self, *args, **kwargs) -> None:
        del args, kwargs
        return None


class BackfillPolicyTest(unittest.TestCase):
    def test_preview_marks_warning_docs_as_review_required_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(Path(tmpdir) / "analysis.db")
            document = make_warning_document()
            pipeline = RunBatchPipeline(
                settings=settings,
                state_reader=object(),
                parsed_db_client=FakeParsedDbClient([document]),
                calendar_db_client=FakeCalendarDbClient(),
                store=AnalysisStore(settings.analysis_db_path),
                selector=Selector(),
                hydrator=FakeHydrator([document]),
                analyze_document=FakeAnalyzeDocument(),
                quality_reviewer=QualityReviewer(settings),
                ops=FakeOps(),
            )

            result = pipeline.preview_backfill(limit=10)

        self.assertEqual(result.ready_to_apply_count, 0)
        self.assertEqual(result.review_required_count, 1)
        self.assertEqual(result.sample_candidates[0]["preview_outcome"], "review_required")

    def test_backfill_skips_warning_docs_until_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(Path(tmpdir) / "analysis.db")
            document = make_warning_document()
            store = AnalysisStore(settings.analysis_db_path)
            analyze_document = FakeAnalyzeDocument()
            pipeline = RunBatchPipeline(
                settings=settings,
                state_reader=object(),
                parsed_db_client=FakeParsedDbClient([document]),
                calendar_db_client=FakeCalendarDbClient(),
                store=store,
                selector=Selector(),
                hydrator=FakeHydrator([document]),
                analyze_document=analyze_document,
                quality_reviewer=QualityReviewer(settings),
                ops=FakeOps(),
            )

            result = pipeline.backfill(limit=10)

            with store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT status, error_type, quality_score
                    FROM analysis_run_items
                    WHERE run_id = ?
                    """,
                    (result.run_id,),
                ).fetchone()

        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(analyze_document.calls, [])
        assert row is not None
        self.assertEqual(row["status"], "skipped_review_required")
        self.assertEqual(row["error_type"], "quality_review_required")
        self.assertEqual(row["quality_score"], 1.0)

    def test_preview_can_opt_in_to_warning_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(Path(tmpdir) / "analysis.db")
            document = make_warning_document()
            pipeline = RunBatchPipeline(
                settings=settings,
                state_reader=object(),
                parsed_db_client=FakeParsedDbClient([document]),
                calendar_db_client=FakeCalendarDbClient(),
                store=AnalysisStore(settings.analysis_db_path),
                selector=Selector(),
                hydrator=FakeHydrator([document]),
                analyze_document=FakeAnalyzeDocument(),
                quality_reviewer=QualityReviewer(settings),
                ops=FakeOps(),
            )

            result = pipeline.preview_backfill(limit=10, allow_warnings=True)

        self.assertEqual(result.ready_to_apply_count, 1)
        self.assertEqual(result.review_required_count, 0)


if __name__ == "__main__":
    unittest.main()
