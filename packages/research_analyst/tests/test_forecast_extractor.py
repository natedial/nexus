from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import (
    AnalysisChunkDraft,
    AssertionDraft,
    EvidenceUnitDraft,
    ForecastExtractionSource,
    HydratedParsedDocument,
    ParsedDocument,
)
from research_analysis_layer.services.forecast_extractor import ForecastExtractor


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


class ForecastExtractorTest(unittest.TestCase):
    def test_extracts_nfp_point_forecast(self) -> None:
        source = ForecastExtractionSource(
            research_id=1,
            file_id="file-1",
            document_hash="hash-1",
            source="Goldman Sachs",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link=None,
            chunk_order=1,
            assertion_order=1,
            assertion_text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            summary_text="NFP preview",
            evidence_text="We forecast +57k jobs in NFP for April 3.",
            qualifier_text=None,
            extraction_confidence="medium",
            created_run_id=12,
        )

        candidates = ForecastExtractor().extract(source)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.indicator_key, "us_nfp")
        self.assertEqual(candidate.event_name, "Nonfarm Payrolls")
        self.assertEqual(candidate.release_date, "2026-04-03")
        self.assertEqual(candidate.forecast_type, "point")
        self.assertEqual(candidate.forecast_value_numeric, 57000.0)
        self.assertEqual(candidate.forecast_unit, "jobs")
        self.assertEqual(candidate.review_status, "approved")

    def test_skips_unanchored_macro_forecast_language(self) -> None:
        source = ForecastExtractionSource(
            research_id=1,
            file_id="file-1",
            document_hash="hash-1",
            source="Goldman Sachs",
            source_date="2026-03-30",
            document_name="macro.pdf",
            document_link=None,
            chunk_order=1,
            assertion_order=1,
            assertion_text="We raised our unemployment rate and inflation forecasts after the oil shock.",
            summary_text="Oil shock inflation feedback",
            evidence_text="We recently lowered GDP growth and raised our unemployment rate and inflation forecasts.",
            qualifier_text=None,
            extraction_confidence="medium",
            created_run_id=12,
        )

        candidates = ForecastExtractor().extract(source)

        self.assertEqual(candidates, [])

    def test_extracts_payroll_preview_without_jobs_word(self) -> None:
        source = ForecastExtractionSource(
            research_id=1,
            file_id="file-1",
            document_hash="hash-1",
            source="Goldman Sachs",
            source_date="2026-02-10",
            document_name="nfp_preview.pdf",
            document_link=None,
            chunk_order=1,
            assertion_order=1,
            assertion_text="January payrolls below consensus: We estimate nonfarm payrolls rose by 45k in January, below consensus of +70k.",
            summary_text="January payrolls below consensus",
            evidence_text="We estimate nonfarm payrolls rose by 45k in January, below consensus of +70k and the two-month average of +53k.",
            qualifier_text=None,
            extraction_confidence="medium",
            created_run_id=12,
        )

        candidates = ForecastExtractor().extract(source)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.indicator_key, "us_nfp")
        self.assertEqual(candidate.period_text, "January 2026")
        self.assertEqual(candidate.forecast_value_numeric, 45000.0)
        self.assertEqual(candidate.forecast_unit, "jobs")
        self.assertEqual(candidate.review_status, "pending")

    def test_extracts_cpi_preview_without_explicit_mom_token(self) -> None:
        source = ForecastExtractionSource(
            research_id=1,
            file_id="file-1",
            document_hash="hash-1",
            source="Goldman Sachs",
            source_date="2026-03-10",
            document_name="cpi_preview.pdf",
            document_link=None,
            chunk_order=1,
            assertion_order=1,
            assertion_text="February CPI Forecast: We expect a 0.17% increase in February core CPI, corresponding to a year-over-year rate of 2.42%.",
            summary_text="February CPI Forecast",
            evidence_text="We expect a 0.17% increase in February core CPI (vs. +0.2% consensus), corresponding to a year-over-year rate of 2.42%.",
            qualifier_text=None,
            extraction_confidence="medium",
            created_run_id=12,
        )

        candidates = ForecastExtractor().extract(source)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.indicator_key, "us_cpi_core_mom")
        self.assertEqual(candidate.period_text, "February 2026")
        self.assertEqual(candidate.forecast_value_numeric, 0.17)
        self.assertEqual(candidate.forecast_unit, "%")

    def test_store_sources_and_candidates_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = make_settings(Path(tmpdir) / "analysis.db")
            store = AnalysisStore(settings.analysis_db_path)
            run = store.create_run("debug", "test", settings)
            document = HydratedParsedDocument(
                document=ParsedDocument(
                    id=5169,
                    document_name="goldman_nfp_preview.pdf",
                    source="Goldman Sachs",
                    source_date="2026-03-30",
                    parsed_data={"metadata": {"document_id": "file-1"}},
                    document_link="https://example.com/doc.pdf",
                    theme_count=1,
                    document_hash="hash-5169",
                ),
                themes=[],
                file_id="file-1",
            )
            chunks = [
                AnalysisChunkDraft(
                    chunk_order=1,
                    chunk_type="forecast_block",
                    title="NFP preview",
                    text="We forecast +57k jobs in NFP for April 3.",
                )
            ]
            evidence_units = [
                EvidenceUnitDraft(
                    chunk_order=1,
                    evidence_order=1,
                    evidence_type="theme_context",
                    text="We forecast +57k jobs in NFP for April 3.",
                )
            ]
            assertions = [
                AssertionDraft(
                    chunk_order=1,
                    assertion_order=1,
                    assertion_type="forecast",
                    text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
                    normalized_text="goldman sachs forecasts 57k jobs in nfp for april 3",
                    summary_text="NFP preview",
                    extraction_confidence="medium",
                    time_horizon="forward",
                )
            ]
            store.replace_document_analysis(
                run_id=run.id,
                parser_updated_at=datetime.fromisoformat("2026-03-30T00:00:00+00:00"),
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
            )
            store.set_document_analysis_version(
                research_id=document.research_id,
                analysis_version=settings.analysis_version,
                run_id=run.id,
            )

            sources = store.get_forecast_extraction_sources()
            self.assertEqual(len(sources), 1)

            candidates = ForecastExtractor().extract(sources[0])
            stored = store.upsert_forecast_candidates(candidates)

            self.assertEqual(stored, 1)
            counts = store.get_analysis_counts()
            self.assertEqual(counts["forecast_candidates"], 1)

            with store._connect() as conn:
                row = conn.execute(
                    """
                    SELECT indicator_key, forecast_value_numeric, release_date, review_status
                    FROM forecast_candidates
                    """
                ).fetchone()

        assert row is not None
        self.assertEqual(row["indicator_key"], "us_nfp")
        self.assertEqual(row["forecast_value_numeric"], 57000.0)
        self.assertEqual(row["release_date"], "2026-04-03")
        self.assertEqual(row["review_status"], "approved")


if __name__ == "__main__":
    unittest.main()
