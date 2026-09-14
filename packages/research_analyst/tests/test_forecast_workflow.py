from __future__ import annotations

import unittest

from research_analysis_layer.models import ForecastCandidateDraft, ForecastCandidateRecord
from research_analysis_layer.services.forecast_matcher import ForecastMatcher


class StubParsedDbClient:
    def __init__(
        self,
        rows: list[dict] | None = None,
        *,
        source_name: str = "economic_events",
        match_source: str = "economic_events",
    ) -> None:
        self.rows = rows or []
        self.uploaded_payload: list[dict] = []
        self.source_name = source_name
        self.match_source = match_source

    def search_economic_events(self, **kwargs) -> list[dict]:
        del kwargs
        return self.rows

    def search_calendar_matches(self, **kwargs) -> list[dict]:
        del kwargs
        return self.rows

    def insert_economic_event_forecasts(self, payload: list[dict]) -> int:
        self.uploaded_payload.extend(payload)
        return len(payload)


class ForecastWorkflowTest(unittest.TestCase):
    def test_matcher_marks_exact_event_match_as_approved(self) -> None:
        candidate = ForecastCandidateDraft(
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Goldman Sachs",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link="https://example.com/nfp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            summary_text="NFP preview",
            evidence_text="We forecast +57k jobs in NFP for April 3.",
            indicator_key="us_nfp",
            event_name="Nonfarm Payrolls",
            country="US",
            period_text="March 2026",
            release_date="2026-04-03",
            forecast_type="point",
            forecast_value_numeric=57000.0,
            forecast_value_low=None,
            forecast_value_high=None,
            forecast_value_text="+57k jobs",
            forecast_unit="jobs",
            qualifier_text=None,
            extraction_confidence="high",
        )
        client = StubParsedDbClient(rows=[{"id": "event-1"}])

        matched = ForecastMatcher().match_candidate(candidate, client)

        self.assertEqual(matched.match_status, "matched_exact")
        self.assertEqual(matched.matched_economic_event_id, "event-1")
        self.assertEqual(matched.matched_calendar_release_id, "event-1")
        self.assertEqual(matched.review_status, "approved")

    def test_matcher_uses_indicator_aliases_for_canonical_event_names(self) -> None:
        candidate = ForecastCandidateDraft(
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Morgan Stanley",
            source_date="2026-03-30",
            document_name="adp.pdf",
            document_link="https://example.com/adp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="MS forecast: +40k.",
            summary_text="ADP preview",
            evidence_text="MS forecast: +40k.",
            indicator_key="us_adp_employment_change",
            event_name="ADP Employment Change",
            country="US",
            period_text="March 2026",
            release_date="2026-04-01",
            forecast_type="point",
            forecast_value_numeric=40000.0,
            forecast_value_low=None,
            forecast_value_high=None,
            forecast_value_text="+40k jobs",
            forecast_unit="jobs",
            qualifier_text=None,
            extraction_confidence="high",
        )
        client = StubParsedDbClient(
            rows=[
                {
                    "id": "event-adp",
                    "event_name": "ADP Employment Weekly",
                    "event_date": "2026-04-01",
                    "country": "US",
                    "period": "Mar",
                    "time_ny": "0815",
                }
            ]
        )

        matched = ForecastMatcher().match_candidate(candidate, client)

        self.assertEqual(matched.match_status, "matched_exact")
        self.assertEqual(matched.matched_economic_event_id, "event-adp")
        self.assertEqual(matched.matched_calendar_release_id, "event-adp")
        self.assertEqual(matched.review_status, "approved")

    def test_matcher_returns_no_event_found_when_no_alias_matches(self) -> None:
        candidate = ForecastCandidateDraft(
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Morgan Stanley",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link="https://example.com/nfp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="Forecast +60k.",
            summary_text="NFP preview",
            evidence_text="Forecast +60k.",
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
        )
        client = StubParsedDbClient(
            rows=[
                {
                    "id": "event-other",
                    "event_name": "MBA Mortgage Applications",
                    "event_date": "2026-04-03",
                    "country": "US",
                    "period": "Mar 27",
                    "time_ny": "0700",
                }
            ]
        )

        matched = ForecastMatcher().match_candidate(candidate, client)

        self.assertEqual(matched.match_status, "no_event_found")
        self.assertIsNone(matched.matched_economic_event_id)
        self.assertEqual(matched.review_status, "approved")

    def test_upload_payload_uses_forecast_table_shape(self) -> None:
        candidate = ForecastCandidateRecord(
            id=7,
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Goldman Sachs",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link="https://example.com/nfp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            summary_text="NFP preview",
            evidence_text="We forecast +57k jobs in NFP for April 3.",
            indicator_key="us_nfp",
            event_name="Nonfarm Payrolls",
            country="US",
            period_text="March 2026",
            release_date="2026-04-03",
            forecast_type="point",
            forecast_value_numeric=57000.0,
            forecast_value_low=None,
            forecast_value_high=None,
            forecast_value_text="+57k jobs",
            forecast_unit="jobs",
            qualifier_text=None,
            extraction_confidence="high",
            match_status="matched_exact",
            matched_economic_event_id="event-1",
            matched_calendar_release_id="event-1",
            matched_calendar_source="economic_events",
            review_status="approved",
            upload_status="not_uploaded",
            created_run_id=9,
            uploaded_at=None,
        )

        payload = ForecastMatcher.to_upload_payload(candidate)

        self.assertEqual(payload["economic_event_id"], "event-1")
        self.assertEqual(payload["parsed_research_id"], 100)
        self.assertEqual(payload["review_status"], "uploaded")

    def test_matcher_maps_release_dates_rows_to_external_release_link(self) -> None:
        candidate = ForecastCandidateDraft(
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Morgan Stanley",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link="https://example.com/nfp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="Forecast +60k.",
            summary_text="NFP preview",
            evidence_text="Forecast +60k.",
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
        )
        client = StubParsedDbClient(
            rows=[
                {
                    "id": "release-date-1",
                    "calendar_release_id": "release-date-1",
                    "calendar_source": "release_dates",
                    "event_name": "Employment Situation",
                    "event_date": "2026-04-03",
                    "country": "US",
                    "period": None,
                    "time_ny": None,
                }
            ],
            source_name="release_dates",
            match_source="release_dates",
        )

        matched = ForecastMatcher().match_candidate(candidate, client)

        self.assertEqual(matched.match_status, "matched_exact")
        self.assertIsNone(matched.matched_economic_event_id)
        self.assertEqual(matched.matched_calendar_release_id, "release-date-1")
        self.assertEqual(matched.matched_calendar_source, "release_dates")

    def test_upload_payload_uses_external_release_fields_for_release_dates_matches(self) -> None:
        candidate = ForecastCandidateRecord(
            id=7,
            research_id=100,
            file_id="file-100",
            document_hash="hash-100",
            source="Goldman Sachs",
            source_date="2026-03-30",
            document_name="nfp.pdf",
            document_link="https://example.com/nfp.pdf",
            chunk_order=1,
            assertion_order=1,
            assertion_text="Goldman Sachs forecasts +57k jobs in NFP for April 3.",
            summary_text="NFP preview",
            evidence_text="We forecast +57k jobs in NFP for April 3.",
            indicator_key="us_nfp",
            event_name="Nonfarm Payrolls",
            country="US",
            period_text="March 2026",
            release_date="2026-04-03",
            forecast_type="point",
            forecast_value_numeric=57000.0,
            forecast_value_low=None,
            forecast_value_high=None,
            forecast_value_text="+57k jobs",
            forecast_unit="jobs",
            qualifier_text=None,
            extraction_confidence="high",
            match_status="matched_exact",
            matched_economic_event_id=None,
            matched_calendar_release_id="release-date-1",
            matched_calendar_source="release_dates",
            review_status="approved",
            upload_status="not_uploaded",
            created_run_id=9,
            uploaded_at=None,
        )

        payload = ForecastMatcher.to_upload_payload(candidate)

        self.assertEqual(payload["calendar_source"], "release_dates")
        self.assertEqual(payload["external_release_id"], "release-date-1")
        self.assertNotIn("economic_event_id", payload)


if __name__ == "__main__":
    unittest.main()
