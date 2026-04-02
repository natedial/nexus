import unittest

from config import parse_trade_conviction_filter
from src.formatter import ReportFormatter


class TradeConvictionFilterTests(unittest.TestCase):
    def setUp(self):
        self.formatter = ReportFormatter()
        self.data = [
            {
                "parsed_data": {
                    "trades": [
                        {"text": "Receive 5y", "conviction": "High"},
                        {"text": "Pay 10y", "conviction": "Medium"},
                        {"text": "Long gamma", "conviction": "Moderate"},
                        {"text": "Fade move", "conviction": "Low"},
                    ]
                },
                "document_name": "Desk note",
                "source": "Goldman Sachs",
                "source_date": "2026-03-17",
            }
        ]

    def test_parse_trade_conviction_filter_normalizes_legacy_low_alias(self):
        self.assertEqual(parse_trade_conviction_filter("low"), "all")

    def test_parse_trade_conviction_filter_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            parse_trade_conviction_filter("hgh")

    def test_aggregate_trades_filters_medium_and_high_only(self):
        trades = self.formatter._aggregate_trades(self.data, conviction_filter="medium")

        self.assertEqual([trade["conviction"] for trade in trades], ["high", "medium", "moderate"])

    def test_format_report_rejects_invalid_conviction_filter(self):
        with self.assertRaises(ValueError):
            self.formatter.format_report(self.data, conviction_filter="hgh")


if __name__ == "__main__":
    unittest.main()
