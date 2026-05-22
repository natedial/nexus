import unittest

from src.synthesizer import Synthesizer


class ExecutiveSummaryValidationTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)
        self.through_lines = [
            {"lead": "Oil shock splits Fed/ECB", "supporting_themes": ["oil shock"]},
            {"lead": "Front-end carry survives", "supporting_themes": ["carry"]},
        ]

    def _valid_paragraphs(self):
        return [
            {
                "text": "Oil shock and carry define the path.",
                "through_line_ids": ["TL1", "TL2"],
                "theme_labels": ["oil shock", "carry"],
                "question_ids": [1, 2, 3, 4, 5, 6],
            }
        ]

    def test_executive_summary_is_extracted_and_cleaned(self):
        data = {
            "executive_summary": [
                "  The week was dominated   by an oil supply shock.  ",
                "Front-end carry remains intact until funding stress bites.",
            ],
            "analysis_paragraphs": self._valid_paragraphs(),
        }
        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertEqual(
            result["executive_summary"],
            [
                "The week was dominated by an oil supply shock.",
                "Front-end carry remains intact until funding stress bites.",
            ],
        )

    def test_executive_summary_defaults_to_empty_when_absent(self):
        data = {"analysis_paragraphs": self._valid_paragraphs()}
        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertEqual(result["executive_summary"], [])

    def test_executive_summary_rejects_more_than_four_paragraphs(self):
        data = {
            "executive_summary": ["a.", "b.", "c.", "d.", "e."],
            "analysis_paragraphs": self._valid_paragraphs(),
        }
        with self.assertRaises(ValueError) as ctx:
            self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertIn("executive_summary", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
