import unittest

from src.synthesizer import Synthesizer


class Stage1BFallbackTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)

    def test_stage1b_failure_keeps_stage1a_through_lines(self):
        raw_through_lines = [
            {"lead": "Oil shock caps hikes", "supporting_themes": ["oil"]},
            {"lead": "Carry survives", "supporting_themes": ["carry"]},
        ]

        # Stage 1A succeeds, Stage 1B (editor) returns None.
        self.synthesizer._stage1_throughlines = lambda input_data: {
            "title": "Test Synthesis",
            "through_lines": raw_through_lines,
        }
        self.synthesizer._stage1_edit_throughlines = lambda title, tls: None
        self.synthesizer._stage2_callouts = lambda tls: []
        # Disable optional analyst stages for this test.
        self.synthesizer._throughline_analyst_config = None
        self.synthesizer._throughline_analyst_config_loaded = True

        result = self.synthesizer._synthesize_with_skills(
            input_data={"themes": [{"label": "oil"}], "trades": []},
            document_count=3,
            scope={},
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result.through_lines), 2)


if __name__ == "__main__":
    unittest.main()
