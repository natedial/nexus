import unittest
from datetime import datetime

from src.formatter import ReportFormatter
from src.report_models import DispatchBatch


class FormatterDispatchBatchTests(unittest.TestCase):
    def setUp(self):
        self.formatter = ReportFormatter()

    def test_format_report_accepts_dispatch_batch(self):
        batch = DispatchBatch.from_dict(
            {
                "batch_key": "2026-04-01:us:rates",
                "analysis_version": "2026-04-01",
                "documents": [
                    {
                        "research_id": 21,
                        "document_name": "Rates Daily",
                        "source": "Goldman Sachs",
                        "source_date": "2026-03-30",
                        "publisher": "Goldman Sachs",
                        "quality": {"score": 91, "passed": True, "warnings": ["sparse_trade_coverage"]},
                        "themes": [
                            {
                                "label": "Higher term premium",
                                "context": "Long-end premium is repricing higher.",
                                "strength": "Primary",
                                "confidence": "High",
                            }
                        ],
                        "trades": [
                            {
                                "text": "Pay 5y rates",
                                "conviction": "High",
                                "timeframe": "weeks",
                            }
                        ],
                        "assertions": [
                            {"summary_text": "Payrolls should miss consensus."},
                            {"summary_text": "Supply pressures term premium."},
                        ],
                    },
                    {
                        "research_id": 22,
                        "document_name": "Macro Weekly",
                        "source": "JPMorgan",
                        "source_date": "2026-03-31",
                        "publisher": "JPMorgan",
                        "quality": {"score": 87, "passed": True},
                        "themes": [
                            {
                                "label": "Higher term premium",
                                "context": "Fiscal supply risk steepens the long end.",
                                "strength": "Primary",
                                "confidence": "High",
                            }
                        ],
                        "trades": [
                            {
                                "text": "Hold 5s30s steepeners",
                                "conviction": "Medium",
                                "timeframe": "weeks",
                            }
                        ],
                        "assertions": [{"summary_text": "Long-end yields should stay biased higher."}],
                    },
                ],
            }
        )

        report = self.formatter.format_report(
            batch,
            active_filters={"region": "US"},
            conviction_filter="all",
        )

        self.assertEqual(report["summary"]["total_documents"], 2)
        self.assertEqual(report["summary"]["analysis_version"], "2026-04-01")
        self.assertEqual(report["summary"]["avg_quality_score"], 89.0)
        self.assertEqual(report["summary"]["warning_documents"], 1)
        self.assertEqual(report["details"][0]["assertions_count"], 2)
        self.assertEqual(report["themes_analysis"][0]["label"], "Higher term premium")
        self.assertEqual(report["themes_analysis"][0]["count"], 2)
        self.assertEqual(len(report["trades"]), 2)
        self.assertEqual(report["source_date_range"]["start"], "2026-03-30")
        self.assertEqual(report["source_date_range"]["end"], "2026-03-31")
        self.assertTrue(report["executive_summary"])
        self.assertGreaterEqual(len(report["executive_summary"]), 3)
        self.assertLessEqual(len(report["executive_summary"]), 10)
        self.assertTrue(any("The batch" in paragraph for paragraph in report["executive_summary"]))
        march_31 = datetime.fromisoformat("2026-03-31").date()
        delta_days = (datetime.now().date() - march_31).days
        if delta_days == 0:
            expected_heading = "TODAY (March 31)"
        elif delta_days == 1:
            expected_heading = "YESTERDAY (March 31)"
        else:
            expected_heading = f"{march_31.strftime('%A').upper()} (March 31)"
        self.assertEqual(report["document_digest"][0]["heading"], expected_heading)
        self.assertIn("Payrolls should miss consensus.", report["document_digest"][1]["entries"][0]["summary"])


if __name__ == "__main__":
    unittest.main()
