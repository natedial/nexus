import unittest

from src.synthesizer import Synthesizer


class ThroughLineBudgetTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)

    def test_lead_is_capped_at_25_words(self):
        long_lead = " ".join(f"word{i}" for i in range(60))
        coerced = self.synthesizer._coerce_through_line({"lead": long_lead})
        self.assertLessEqual(len(coerced["lead"].split()), 25)

    def test_short_lead_is_left_alone(self):
        coerced = self.synthesizer._coerce_through_line(
            {"lead": "Oil shock caps Fed hikes"}
        )
        self.assertEqual(coerced["lead"], "Oil shock caps Fed hikes")


if __name__ == "__main__":
    unittest.main()
