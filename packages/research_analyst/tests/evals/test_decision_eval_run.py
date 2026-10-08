"""Tests for the standardized decision-eval run directory."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.decision_artifacts import write_shadow_artifact
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_eval_run import (
    TOP_LEVEL_OUTPUTS,
    run_decision_eval,
)
from research_analysis_layer.evals.decision_metrics import estimate_usage_cost
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel


class DecisionEvalRunTest(unittest.TestCase):
    def test_run_directory_contains_separated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            live_root = Path(tmp) / "live"
            live_root.mkdir()
            live_artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
                [
                    AssertionDraft(
                        chunk_order=9,
                        assertion_order=1,
                        assertion_type="forecast",
                        text="Growth will slow next year.",
                        normalized_text=normalize_text("Growth will slow next year."),
                        summary_text="Growth will slow next year.",
                    )
                ],
                document_key="doc_live",
            )
            write_shadow_artifact(live_artifact, live_root, prefix="shadow_doc_live")
            run_decision_eval(
                output_dir=output,
                provider="fake",
                live_artifact_root=live_root,
                packet_size=8,
                repeatability_runs=2,
                command_arguments={"provider": "fake"},
            )
            for name in TOP_LEVEL_OUTPUTS:
                self.assertTrue((output / name).is_file(), name)
            self.assertTrue(any((output / "artifacts" / "fixture").glob("*.json")))
            self.assertTrue(any((output / "artifacts" / "live").glob("*.json")))

            gold = json.loads((output / "gold_metrics.json").read_text(encoding="utf-8"))
            silver = json.loads(
                (output / "silver_agreement.json").read_text(encoding="utf-8")
            )
            consistency = json.loads(
                (output / "consistency_report.json").read_text(encoding="utf-8")
            )
            manifest = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
            summary = (output / "SUMMARY.md").read_text(encoding="utf-8")
            packet = (output / "review_packet.md").read_text(encoding="utf-8")

            self.assertEqual(gold["schema_version"], "decision-gold-metrics-v1")
            self.assertGreater(gold["fixture"]["unit_count"], 0)
            self.assertEqual(gold["live"]["labeled_unit_count"], 0)
            self.assertIn("never gold", " ".join(silver["notes"]))
            self.assertIn("compound_decomposition", consistency["families"])
            self.assertTrue(manifest["safety"]["gold_silver_consistency_separated"])
            self.assertFalse(manifest["safety"]["production_routing_changed"])
            self.assertIn("ineligible", summary.lower())
            self.assertIn("gold_metrics.json", summary)
            self.assertLessEqual(packet.count("\n## "), 20)
            queue_lines = [
                line
                for line in (output / "review_queue.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertLessEqual(len(queue_lines), 8)

    def test_fake_provider_cost_is_zero(self) -> None:
        cost = estimate_usage_cost({"input_tokens": 1000}, provider="fake")
        self.assertEqual(cost["estimated_usd"], 0.0)

    def test_jev_cost_uses_provisional_rates(self) -> None:
        cost = estimate_usage_cost(
            {"input_tokens": 28_700, "output_tokens": 0},
            provider="jev",
        )
        self.assertIsNotNone(cost["estimated_usd"])
        self.assertGreater(cost["estimated_usd"], 0.0)
        self.assertIn("provisional", cost["pricing_source"])

    def test_packet_size_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_decision_eval(output_dir=Path(tmp) / "run", packet_size=21)


if __name__ == "__main__":
    unittest.main()
