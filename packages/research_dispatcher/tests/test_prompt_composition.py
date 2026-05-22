import unittest

from src.synthesizer import _load_prompt


class PromptCompositionTests(unittest.TestCase):
    def test_synthesis_prompt_includes_consensus_definitions(self):
        prompt = _load_prompt("synthesis.md")
        self.assertIn("strong_consensus", prompt)
        self.assertIn("moderate_consensus", prompt)

    def test_throughline_synthesizer_prompt_includes_consensus_definitions(self):
        prompt = _load_prompt("throughline_synthesizer.md")
        self.assertIn("strong_consensus", prompt)

    def test_both_prompts_share_identical_consensus_block(self):
        from pathlib import Path
        from src.synthesizer import COMPONENTS_PATH

        block = (COMPONENTS_PATH / "consensus_levels.md").read_text().strip()
        self.assertIn("strong_consensus", block)
        self.assertIn(block, _load_prompt("synthesis.md"))
        self.assertIn(block, _load_prompt("throughline_synthesizer.md"))


if __name__ == "__main__":
    unittest.main()
