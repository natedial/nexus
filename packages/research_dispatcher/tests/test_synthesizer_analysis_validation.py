import unittest

from src.synthesizer import Synthesizer


class SynthesizerAnalysisValidationTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(
            anthropic_api_key=None,
            openai_api_key=None,
            deepinfra_api_key=None,
            use_skill_pipeline=True,
        )
        self.through_lines = [
            {
                "lead": "Oil shock splits Fed/ECB, caps hikes, revives stagflation",
                "supporting_themes": ["oil shock", "stagflation"],
            },
            {
                "lead": "Front-end carry survives until funding stress forces repricing",
                "supporting_themes": ["carry", "funding stress"],
            },
        ]

    def test_coerce_analysis_result_accepts_stable_through_line_ids(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_ids": ["TL1"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3, 4, 5],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_ids": ["TL2"],
                    "theme_labels": ["carry"],
                    "question_ids": [6, 7, 8, 9, 10],
                },
            ]
        }

        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)

        self.assertEqual(len(result["analysis_paragraphs"]), 2)
        self.assertEqual(
            result["analysis_paragraphs"][0]["through_line_leads"],
            ["Oil shock splits Fed/ECB, caps hikes, revives stagflation"],
        )
        self.assertEqual(result["analysis_paragraphs"][0]["through_line_ids"], ["TL1"])

    def test_coerce_analysis_result_fuzzily_resolves_minor_lead_variants(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_leads": ["Oil shock splits Fed ECB caps hikes revives stagflation"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3, 4, 5],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_leads": ["Front end carry survives until funding stress forces repricing"],
                    "theme_labels": ["carry"],
                    "question_ids": [6, 7, 8, 9, 10],
                },
            ]
        }

        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)

        self.assertEqual(
            result["analysis_paragraphs"][1]["through_line_leads"],
            ["Front-end carry survives until funding stress forces repricing"],
        )


    def test_coerce_analysis_result_rejects_fewer_than_six_questions(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_ids": ["TL1"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_ids": ["TL2"],
                    "theme_labels": ["carry"],
                    "question_ids": [4, 5],
                },
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertIn("at least 6", str(ctx.exception))

    def test_coerce_analysis_result_accepts_six_questions(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_ids": ["TL1"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_ids": ["TL2"],
                    "theme_labels": ["carry"],
                    "question_ids": [4, 5, 6],
                },
            ]
        }
        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertEqual(len(result["analysis_paragraphs"]), 2)

    def test_stage1c_uses_llm_json_adapter(self):
        class FakeClient:
            def generate_json(self, **kwargs):
                return {
                    "analysis_paragraphs": [
                        {
                            "text": "Oil shock and carry risks define the repricing path.",
                            "through_line_ids": ["TL1", "TL2"],
                            "theme_labels": ["oil shock", "carry"],
                            "question_ids": [1, 2, 3, 4, 5, 6],
                        }
                    ]
                }

        self.synthesizer.client = FakeClient()

        result = self.synthesizer._stage1c_analyze_throughlines(
            title="Adapter Test",
            through_lines=self.through_lines,
            input_data={"themes": [], "trades": []},
            scope={},
        )

        self.assertEqual(len(result["analysis_paragraphs"]), 1)


if __name__ == "__main__":
    unittest.main()
