import unittest

from src.formatter import ReportFormatter


class TradeTextLevelPreservationTests(unittest.TestCase):
    def setUp(self):
        self.formatter = ReportFormatter()

    def test_price_target_after_comma_is_preserved(self):
        text = "Buy Brent crude oil, targeting $90 per barrel into year-end"
        result = self.formatter._summary_trade_text(text)
        self.assertIn("90", result)

    def test_no_hardcoded_rewrite_collapses_brent_trade(self):
        text = "Buy Brent crude oil in anticipation of prices reaching $92"
        result = self.formatter._summary_trade_text(text)
        # Must keep the level, not collapse to the old hardcoded "Buy Brent crude".
        self.assertIn("92", result)

    def test_clause_with_basis_points_survives(self):
        text = "Receive 5y5y, looking for a 25bp rally over the next month"
        result = self.formatter._summary_trade_text(text)
        self.assertIn("25bp", result)

    def test_plain_trade_without_levels_still_returned(self):
        text = "Buy 10y Treasuries"
        result = self.formatter._summary_trade_text(text)
        self.assertEqual(result, "Buy 10y Treasuries")


if __name__ == "__main__":
    unittest.main()
