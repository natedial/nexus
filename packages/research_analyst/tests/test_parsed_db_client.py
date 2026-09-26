from __future__ import annotations

import unittest
from datetime import date

from research_analysis_layer.db.calendar_db_client import CalendarDbClient
from research_analysis_layer.db.parsed_db_client import ParsedDbClient


class RecordingParsedDbClient(ParsedDbClient):
    def __init__(self) -> None:
        super().__init__("https://example.supabase.co", "secret")
        self.recorded_table = None
        self.recorded_params = None

    def _get(self, table, params):
        self.recorded_table = table
        self.recorded_params = params
        return []


class ParsedDbClientTest(unittest.TestCase):
    def test_document_from_row_coerces_source_date_to_iso_string(self) -> None:
        document = ParsedDbClient._document_from_row(
            {
                "id": 42,
                "document_name": "rates-outlook.pdf",
                "source": "Example Bank",
                "source_date": date(2026, 3, 27),
                "parsed_data": {},
            }
        )
        self.assertEqual(document.source_date, "2026-03-27")

    def test_search_documents_uses_combined_filters(self) -> None:
        client = RecordingParsedDbClient()
        client.search_documents(
            date_from="2026-03-27",
            date_to="2026-03-27",
            source="Goldman Sachs",
            limit=10,
        )
        self.assertEqual(client.recorded_table, "parsed_research")
        self.assertIn(("limit", "10"), client.recorded_params)
        self.assertIn(
            (
                "and",
                "(source_date.gte.2026-03-27,source_date.lte.2026-03-27,source.ilike.*Goldman Sachs*)",
            ),
            client.recorded_params,
        )

    def test_search_economic_events_uses_event_date_and_country_filters(self) -> None:
        client = RecordingParsedDbClient()

        client.search_economic_events(
            release_date="2026-04-03",
            country="US",
            limit=25,
        )

        self.assertEqual(client.recorded_table, "economic_events")
        self.assertIn(("select", "id,event_name,event_date,country,period,time_ny"), client.recorded_params)
        self.assertIn(("order", "event_date.asc,time_ny.asc,event_name.asc"), client.recorded_params)
        self.assertIn(("limit", "25"), client.recorded_params)
        self.assertIn(("and", "(event_date.eq.2026-04-03,country.eq.US)"), client.recorded_params)


class CalendarDbClientTest(unittest.TestCase):
    def test_search_calendar_matches_uses_legacy_economic_events_by_default(self) -> None:
        client = CalendarDbClient(
            "https://example.supabase.co",
            "secret",
            match_source="economic_events",
            source_name="economic_events",
        )

        calls: list[tuple[str, object]] = []

        def fake_search(**kwargs):
            calls.append(("economic_events", kwargs))
            return [{"id": "event-1"}]

        client.search_economic_events = fake_search  # type: ignore[method-assign]

        rows = client.search_calendar_matches(
            release_date="2026-04-03",
            country="US",
            limit=25,
        )

        self.assertEqual(rows, [{"id": "event-1"}])
        self.assertEqual(
            calls,
            [
                (
                    "economic_events",
                    {
                        "release_date": "2026-04-03",
                        "country": "US",
                        "limit": 25,
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
