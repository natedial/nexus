from __future__ import annotations

from pathlib import Path
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.models import (
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
)
from research_analysis_layer.services.quality import QualityReviewer


def make_settings() -> Settings:
    return Settings(
        analysis_db_url="sqlite:///data/analysis.db",
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


def make_document(
    *,
    source: str = "J.P. Morgan",
    document_name: str = "2026-03-30_JPM_macro_outlook.pdf",
    full_text: str | None = None,
    include_excerpts: bool = True,
) -> HydratedParsedDocument:
    parsed_data = {
        "full_text": full_text or ("Macro outlook " * 200),
        "metadata": {"document_id": "file-1"},
    }
    document = ParsedDocument(
        id=1,
        document_name=document_name,
        source=source,
        source_date="2026-03-30",
        parsed_data=parsed_data,
        theme_count=2,
        document_hash="hash123",
    )
    theme_one = ParsedTheme(
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
    )
    theme_two = ParsedTheme(
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
    )
    excerpts_one = [
        ParsedExcerpt(id=101, theme_id=10, excerpt_order=1, excerpt_text="A" * 120),
        ParsedExcerpt(id=102, theme_id=10, excerpt_order=2, excerpt_text="B" * 120),
    ]
    excerpts_two = [
        ParsedExcerpt(id=103, theme_id=11, excerpt_order=1, excerpt_text="C" * 120),
        ParsedExcerpt(id=104, theme_id=11, excerpt_order=2, excerpt_text="D" * 120),
    ]
    return HydratedParsedDocument(
        document=document,
        themes=[
            HydratedTheme(theme=theme_one, excerpts=excerpts_one if include_excerpts else []),
            HydratedTheme(theme=theme_two, excerpts=excerpts_two if include_excerpts else []),
        ],
        file_id="file-1",
    )


class QualityReviewerTest(unittest.TestCase):
    def test_passes_good_document(self) -> None:
        reviewer = QualityReviewer(make_settings())
        report = reviewer.review(make_document())
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.score, 0.6)

    def test_blocks_missing_source_and_short_text(self) -> None:
        reviewer = QualityReviewer(make_settings())
        report = reviewer.review(make_document(source="Unknown", full_text="short text"))
        self.assertFalse(report.passed)
        self.assertIn("missing_or_unknown_source", report.blocking_issues)
        self.assertIn("full_text_too_short", report.blocking_issues)

    def test_known_abbreviation_does_not_raise_filename_warning(self) -> None:
        reviewer = QualityReviewer(make_settings())
        report = reviewer.review(
            make_document(
                source="Goldman Sachs",
                document_name="2026-03-27_GS_macro_views.pdf",
            )
        )
        self.assertNotIn("source_filename_mismatch", report.warnings)

    def test_conflicting_institution_blocks_document(self) -> None:
        reviewer = QualityReviewer(make_settings())
        report = reviewer.review(
            make_document(
                source="Bank of America",
                document_name="2026-03-27_JPM_on_ECB_rates.pdf",
            )
        )
        self.assertIn("source_filename_mismatch", report.warnings)
        self.assertIn("source_filename_conflict", report.blocking_issues)


if __name__ == "__main__":
    unittest.main()
