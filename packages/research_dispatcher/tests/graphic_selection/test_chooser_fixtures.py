"""End-to-end Fake chooser against shape-only fixtures."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.graphic_selection.chooser import GraphicChooser, choose_graphics
from src.graphic_selection.cli import load_concept_blocks
from src.graphic_selection.fake_decision_model import FakeDecisionModel
from src.graphic_selection.factory import DecisionModelConfigError, build_decision_model
from src.graphic_selection.models import ConceptBlock

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "graphic_selection"
    / "concept_blocks.jsonl"
)


class ChooserFixtureTests(unittest.TestCase):
    def test_fixtures_match_expected_patterns(self):
        blocks = load_concept_blocks(FIXTURES)
        self.assertGreaterEqual(len(blocks), 20)
        artifact = GraphicChooser(FakeDecisionModel()).choose(
            blocks, document_key="fixture-suite"
        )
        self.assertEqual(len(artifact.units), len(blocks))
        for unit, block in zip(artifact.units, blocks, strict=True):
            emit = unit.decision.emit["pattern_id"]
            self.assertEqual(
                emit,
                block.expected_pattern_id,
                msg=f"{block.concept_id}: emit={emit} expected={block.expected_pattern_id}",
            )
            # Shape-only: no significance keys in nouls.
            self.assertNotIn("deserves_chart", unit.decision.nouls)
            self.assertNotIn("is_significant", unit.decision.nouls)

    def test_choose_graphics_default_fake(self):
        blocks = [
            ConceptBlock(
                concept_id="x",
                concept_text="prose only",
                data_shape="none",
                available_fields=[],
            )
        ]
        artifact = choose_graphics(blocks, provider="fake")
        self.assertEqual(artifact.provider, "fake")
        self.assertEqual(artifact.units[0].decision.emit["pattern_id"], "prose")

    def test_factory_rejects_unknown_provider(self):
        with self.assertRaises(DecisionModelConfigError):
            build_decision_model(provider="openai")

    def test_factory_jev_fail_closed_without_config(self):
        with self.assertRaises(DecisionModelConfigError):
            build_decision_model(provider="jev")

    def test_artifact_json_roundtrip(self):
        blocks = load_concept_blocks(FIXTURES)[:3]
        artifact = GraphicChooser(FakeDecisionModel()).choose(blocks)
        payload = json.loads(artifact.model_dump_json())
        self.assertEqual(payload["schema_version"], "graphic-selection-artifact-v1")
        self.assertEqual(payload["question_set_version"], "graphic-question-set-v1")


if __name__ == "__main__":
    unittest.main()
