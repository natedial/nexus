import tempfile
import unittest
from pathlib import Path

from src.html_generator import HtmlReportGenerator


def _sample_report() -> dict:
    return {
        "title": "Research Dispatch",
        "generated_at": "2026-09-30 10:00:00",
        "source_date_range": {"start": "2026-09-22", "end": "2026-09-29"},
        "active_filters": {"region": "US", "asset_focus": "rates"},
        "summary": {
            "total_documents": 3,
            "by_source": {"GS": 2, "JPM": 1},
        },
        "executive_summary": ["Front-end pricing remains the hinge."],
        "analysis_paragraphs": [{"text": "Dealers lean long duration into supply."}],
        "street_agrees_splits": {
            "lines": ["GS and MS agree Fed on hold (2 houses)"],
        },
        "synthesis_delta": {
            "summary": "Two through-lines refreshed versus prior week.",
            "baseline_available": True,
            "baseline_label": "2026-09-15 – 2026-09-21",
            "sections": [
                {
                    "title": "New",
                    "items": ["Supply indigestion into mid-curve."],
                }
            ],
        },
        "through_lines": [
            {
                "lead": "Post-SLR dealer capacity",
                "detail": "Balance-sheet headroom remains the binding constraint.",
                "source": "GS",
            }
        ],
        "callouts": [
            {
                "source_through_line": "Post-SLR dealer capacity",
                "content": "Inventory absorption is slower than last quarter.",
                "source": "JPM Rates",
            }
        ],
        "document_digest": [
            {
                "heading": "Mon Sep 29",
                "entries": [
                    {
                        "source": "GS",
                        "title": "US Rates Daily",
                        "summary": "Curve steeper on supply.",
                    }
                ],
            }
        ],
        "themes_by_through_line": [
            {
                "lead": "Post-SLR dealer capacity",
                "themes": [
                    {
                        "label": "Dealer balance sheet",
                        "context": "SLR still binds inventory.",
                        "strength": "strong",
                        "source": "GS",
                    }
                ],
                "overflow_count": 0,
            }
        ],
        "trades": [
            {
                "text": "Pay 2s10s",
                "conviction": "high",
                "exposure": "curve",
                "timeframe": "2w",
                "rationale": "Supply into a thin dealer bid.",
                "trigger_levels": {"entry": "12bp"},
                "source": "GS",
                "document": "US Rates Daily.pdf",
                "date": "2026-09-29",
            }
        ],
        "economic_calendar": {
            "Wed": [
                {
                    "time": "08:30",
                    "event": "Core PCE",
                    "consensus": "0.2%",
                }
            ]
        },
        "supply_calendar": {
            "Thu": [
                {
                    "time": "13:00",
                    "description": "10Y note",
                    "size": "39",
                }
            ]
        },
        "details": [
            {
                "source": "GS",
                "document_name": "US Rates Daily.pdf",
                "source_date": "2026-09-29",
            }
        ],
    }


class HtmlReportGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.generator = HtmlReportGenerator(output_dir=self.tmpdir.name)

    def test_manifest_loads_pattern_ids(self):
        ids = self.generator.pattern_ids()
        self.assertIn("metric_strip", ids)
        self.assertIn("context_table", ids)
        self.assertIn("annotation", ids)

    def test_compose_css_includes_kit_and_section_chrome(self):
        css = self.generator.compose_css({"metric_strip"})
        self.assertIn("--ink:", css)
        self.assertIn(".metric-strip", css)
        self.assertIn(".throughline-card", css)
        self.assertIn("@media print", css)

    def test_render_includes_core_sections_and_unicode(self):
        report = _sample_report()
        unicode_lead = "Post‑SLR dealer capacity"
        report["through_lines"][0]["lead"] = unicode_lead
        report["callouts"][0]["source_through_line"] = unicode_lead
        html = self.generator.render(report)

        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("Executive Summary", html)
        self.assertIn("Market Analysis", html)
        self.assertIn("Change Tracking", html)
        self.assertIn("Where the Street Agrees", html)
        self.assertIn("Through Lines", html)
        self.assertIn("Document Digest", html)
        self.assertIn("Thematic Analysis", html)
        self.assertIn("Trade Recommendations", html)
        self.assertIn("Economic Calendar", html)
        self.assertIn("Treasury Supply Calendar", html)
        self.assertIn("Detailed Records", html)
        self.assertIn("Post‑SLR dealer capacity", html)
        self.assertIn('data-pattern="metric_strip"', html)
        self.assertIn('data-pattern="context_table"', html)
        self.assertIn('data-pattern="annotation"', html)
        self.assertIn("Inventory absorption is slower", html)
        self.assertIn("[HIGH]", html)

    def test_street_section_omitted_without_payload(self):
        report = _sample_report()
        report.pop("street_agrees_splits")
        html = self.generator.render(report)
        self.assertNotIn("Where the Street Agrees", html)

    def test_generate_writes_file(self):
        path = self.generator.generate(_sample_report(), "sample.html")
        self.assertTrue(Path(path).is_file())
        content = Path(path).read_text(encoding="utf-8")
        self.assertIn("Research Dispatch", content)
        self.assertGreater(len(content), 1000)


if __name__ == "__main__":
    unittest.main()
