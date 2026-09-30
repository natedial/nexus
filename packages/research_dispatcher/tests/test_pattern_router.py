import unittest

from src.pattern_router import PatternRouter


class PatternRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = PatternRouter()

    def test_cover_metrics_applies_metric_strip(self):
        report = {
            "summary": {"total_documents": 3, "by_source": {"GS": 2}},
            "source_date_range": {"start": "2026-09-01", "end": "2026-09-08"},
            "through_lines": [{"lead": "A"}],
        }
        resolved = self.router.resolve_report(report)
        self.assertEqual(resolved["cover_metrics"]["applied"], "metric_strip")

    def test_calendars_use_context_table(self):
        report = {
            "summary": {},
            "economic_calendar": {"Wed": [{"time": "08:30", "event": "PCE", "consensus": "0.2%"}]},
            "supply_calendar": {},
            "details": [],
        }
        resolved = self.router.resolve_report(report)
        self.assertEqual(resolved["economic_calendar"]["applied"], "context_table")
        self.assertIsNone(resolved["supply_calendar"]["applied"])

    def test_deferred_delta_stays_prose(self):
        report = {
            "summary": {},
            "synthesis_delta": {
                "sections": [{"title": "New", "items": ["Narrative only"]}],
            },
        }
        resolved = self.router.resolve_report(report)
        self.assertEqual(resolved["synthesis_delta"]["status"], "deferred")
        self.assertIsNone(resolved["synthesis_delta"]["applied"])
        self.assertEqual(resolved["synthesis_delta"]["fallback"], "prose")

    def test_routing_file_lists_prose_slots(self):
        prose = self.router.routing.get("prose_slots") or []
        self.assertIn("executive_summary", prose)
        self.assertIn("through_lines", prose)


if __name__ == "__main__":
    unittest.main()
