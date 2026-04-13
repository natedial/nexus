from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from research_analysis_layer.config import Settings
from research_analysis_layer.main import (
    command_extract_forecasts,
    command_sync_forecasts,
    command_upload_forecasts,
)
from research_analysis_layer.models import (
    ForecastCandidateDraft,
    ForecastCandidateRecord,
    ForecastExtractionSource,
)


def make_settings() -> Settings:
    return Settings(
        analysis_db_url="sqlite:///tmp/test-analysis.db",
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
        assertion_extractor_version="deterministic-theme-v2",
        resolver_version="bootstrap-v2",
        request_timeout_seconds=30,
        min_full_text_chars=500,
        min_quality_score=0.6,
        min_usable_theme_ratio=0.6,
        backfill_require_warning_free=True,
    )


class StubStore:
    def __init__(self) -> None:
        self.deleted = False
        self.upserted_candidates = None
        self.upload_result_calls = []
        self.list_forecast_candidates_result = [
            ForecastCandidateRecord(
                id=10,
                research_id=5194,
                file_id="file-5194",
                document_hash="hash-5194",
                source="Morgan Stanley",
                source_date="2026-03-29",
                document_name="ms.pdf",
                document_link="https://example.com/ms.pdf",
                chunk_order=1,
                assertion_order=1,
                assertion_text="Forecast +60k jobs.",
                summary_text="NFP preview",
                evidence_text="Forecast +60k jobs.",
                indicator_key="us_nfp",
                event_name="Nonfarm Payrolls",
                country="US",
                period_text="March 2026",
                release_date="2026-04-03",
                forecast_type="point",
                forecast_value_numeric=60000.0,
                forecast_value_low=None,
                forecast_value_high=None,
                forecast_value_text="+60k jobs",
                forecast_unit="jobs",
                qualifier_text=None,
                extraction_confidence="high",
                match_status="no_event_found",
                matched_economic_event_id=None,
                matched_calendar_release_id=None,
                matched_calendar_source="economic_events",
                review_status="approved",
                review_notes=None,
                upload_status="not_uploaded",
                uploaded_at=None,
                created_run_id=14,
            )
        ]

    def delete_forecast_candidates(self, research_id=None) -> int:
        del research_id
        self.deleted = True
        return 5

    def get_forecast_extraction_sources(self, **kwargs):
        del kwargs
        return [
            ForecastExtractionSource(
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
        ]

    def upsert_forecast_candidates(self, candidates) -> int:
        self.upserted_candidates = list(candidates)
        return len(candidates)

    def list_analyzed_documents(self, **kwargs):
        del kwargs
        return []

    def list_forecast_candidates(self, **kwargs):
        del kwargs
        return self.list_forecast_candidates_result

    def mark_forecast_upload_result(
        self,
        *,
        candidate_id,
        upload_status,
        review_status=None,
        review_notes=None,
    ):
        self.upload_result_calls.append(
            {
                "candidate_id": candidate_id,
                "upload_status": upload_status,
                "review_status": review_status,
                "review_notes": review_notes,
            }
        )


class StubParsedDbClient:
    def __init__(self) -> None:
        self.uploaded_payload = []

    def search_economic_events(self, **kwargs):
        del kwargs
        return [{"id": "event-1"}]

    def fetch_documents(self, ids):
        del ids
        return []

    def insert_economic_event_forecasts(self, payload):
        self.uploaded_payload.extend(payload)
        return len(payload)


class StubPipeline:
    def __init__(self) -> None:
        self.store = StubStore()
        self.parsed_db_client = StubParsedDbClient()
        self.calendar_db_client = StubParsedDbClient()


class ForecastCliTest(unittest.TestCase):
    def test_extract_forecasts_dry_run_skips_delete_and_store(self) -> None:
        pipeline = StubPipeline()
        buffer = io.StringIO()

        with patch("research_analysis_layer.main.build_app", return_value=pipeline):
            with redirect_stdout(buffer):
                exit_code = command_extract_forecasts(
                    make_settings(),
                    limit=100,
                    research_id=None,
                    rebuild=True,
                    dry_run=True,
                )

        self.assertEqual(exit_code, 0)
        self.assertFalse(pipeline.store.deleted)
        self.assertIsNone(pipeline.store.upserted_candidates)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["stored_count"], 0)
        self.assertEqual(payload["would_store_count"], 1)

    def test_upload_forecasts_uploads_unmatched_candidates(self) -> None:
        """Candidates with no matched reference are uploaded with economic_event_id=None."""
        pipeline = StubPipeline()
        buffer = io.StringIO()

        with patch("research_analysis_layer.main.build_app", return_value=pipeline):
            with redirect_stdout(buffer):
                exit_code = command_upload_forecasts(
                    make_settings(),
                    limit=25,
                )

        self.assertEqual(exit_code, 0)
        # The candidate was uploaded, not skipped
        self.assertEqual(len(pipeline.parsed_db_client.uploaded_payload), 1)
        uploaded = pipeline.parsed_db_client.uploaded_payload[0]
        self.assertEqual(uploaded["indicator_key"], "us_nfp")
        self.assertIsNone(uploaded.get("economic_event_id"))
        self.assertEqual(
            pipeline.store.upload_result_calls,
            [
                {
                    "candidate_id": 10,
                    "upload_status": "uploaded",
                    "review_status": "uploaded",
                    "review_notes": None,
                }
            ],
        )
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["uploaded_count"], 1)
        self.assertEqual(payload["skipped_count"], 0)
        self.assertEqual(payload["failed_count"], 0)

    def test_upload_forecasts_treats_conflict_as_already_uploaded(self) -> None:
        pipeline = StubPipeline()
        pipeline.store.list_forecast_candidates_result = [
            ForecastCandidateRecord(
                id=11,
                research_id=5194,
                file_id="file-5194",
                document_hash="hash-5194",
                source="Morgan Stanley",
                source_date="2026-03-29",
                document_name="ms.pdf",
                document_link="https://example.com/ms.pdf",
                chunk_order=1,
                assertion_order=1,
                assertion_text="Forecast +40 jobs.",
                summary_text="ADP preview",
                evidence_text="Forecast +40 jobs.",
                indicator_key="us_adp_employment_change",
                event_name="ADP Employment Change",
                country="US",
                period_text="March 2026",
                release_date="2026-04-01",
                forecast_type="point",
                forecast_value_numeric=40.0,
                forecast_value_low=None,
                forecast_value_high=None,
                forecast_value_text="40",
                forecast_unit="jobs",
                qualifier_text=None,
                extraction_confidence="high",
                match_status="matched_exact",
                matched_economic_event_id=None,
                matched_calendar_release_id="800",
                matched_calendar_source="scrivener",
                review_status="approved",
                review_notes=None,
                upload_status="not_uploaded",
                uploaded_at=None,
                created_run_id=14,
            )
        ]

        class ConflictParsedDbClient(StubParsedDbClient):
            def insert_economic_event_forecasts(self, payload):
                self.uploaded_payload.extend(payload)
                raise HTTPError(
                    url="https://example.supabase.co/rest/v1/economic_event_forecasts",
                    code=409,
                    msg="Conflict",
                    hdrs=None,
                    fp=None,
                )

        pipeline.parsed_db_client = ConflictParsedDbClient()
        buffer = io.StringIO()

        with patch("research_analysis_layer.main.build_app", return_value=pipeline):
            with redirect_stdout(buffer):
                exit_code = command_upload_forecasts(
                    make_settings(),
                    limit=25,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            pipeline.store.upload_result_calls,
            [
                {
                    "candidate_id": 11,
                    "upload_status": "uploaded",
                    "review_status": "uploaded",
                    "review_notes": "already_uploaded_conflict",
                }
            ],
        )
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["uploaded_count"], 1)
        self.assertEqual(payload["failed_count"], 0)

    def test_sync_forecasts_extracts_and_uploads_approved_matches(self) -> None:
        pipeline = StubPipeline()
        pipeline.store.list_forecast_candidates_result = [
            ForecastCandidateRecord(
                id=11,
                research_id=5194,
                file_id="file-5194",
                document_hash="hash-5194",
                source="Morgan Stanley",
                source_date="2026-03-29",
                document_name="ms.pdf",
                document_link="https://example.com/ms.pdf",
                chunk_order=1,
                assertion_order=1,
                assertion_text="Forecast +60k jobs.",
                summary_text="NFP preview",
                evidence_text="Forecast +60k jobs.",
                indicator_key="us_nfp",
                event_name="Nonfarm Payrolls",
                country="US",
                period_text="March 2026",
                release_date="2026-04-03",
                forecast_type="point",
                forecast_value_numeric=60000.0,
                forecast_value_low=None,
                forecast_value_high=None,
                forecast_value_text="+60k jobs",
                forecast_unit="jobs",
                qualifier_text=None,
                extraction_confidence="high",
                match_status="matched_exact",
                matched_economic_event_id="event-1",
                review_status="approved",
                review_notes=None,
                upload_status="not_uploaded",
                uploaded_at=None,
                created_run_id=14,
            )
        ]
        buffer = io.StringIO()

        with patch("research_analysis_layer.main.build_app", return_value=pipeline):
            with redirect_stdout(buffer):
                exit_code = command_sync_forecasts(
                    make_settings(),
                    extract_limit=None,
                    upload_limit=250,
                )

        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(pipeline.store.upserted_candidates)
        self.assertEqual(len(pipeline.store.upserted_candidates), 1)
        extracted = pipeline.store.upserted_candidates[0]
        self.assertIsInstance(extracted, ForecastCandidateDraft)
        self.assertEqual(extracted.review_status, "approved")
        self.assertEqual(extracted.matched_economic_event_id, "event-1")
        self.assertEqual(len(pipeline.parsed_db_client.uploaded_payload), 1)
        self.assertEqual(
            pipeline.store.upload_result_calls,
            [
                {
                    "candidate_id": 11,
                    "upload_status": "uploaded",
                    "review_status": "uploaded",
                    "review_notes": None,
                }
            ],
        )
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["extract"]["stored_count"], 1)
        self.assertEqual(payload["upload"]["uploaded_count"], 1)


if __name__ == "__main__":
    unittest.main()
