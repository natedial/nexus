"""Tests for golden dataset."""

import json
import unittest
from pathlib import Path

from research_analysis_layer.evals.runner import (
    load_golden_annotations,
    load_golden_document,
)


class TestGoldenDataset(unittest.TestCase):
    """Tests for golden dataset integrity."""

    @classmethod
    def setUpClass(cls):
        cls.golden_path = Path(__file__).parent.parent.parent / "evals" / "golden"

    def test_annotations_file_exists(self):
        annotations_path = self.golden_path / "annotations.jsonl"
        self.assertTrue(annotations_path.exists(), "annotations.jsonl must exist")

    def test_annotations_are_valid_jsonl(self):
        annotations_path = self.golden_path / "annotations.jsonl"
        with open(annotations_path, "r") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError as e:
                    self.fail(f"Line {i} is not valid JSON: {e}")
                self.assertIn("document_id", doc, f"Line {i} missing document_id")
                self.assertIn("document_path", doc, f"Line {i} missing document_path")
                self.assertIn("expected", doc, f"Line {i} missing expected")

    def test_minimum_10_documents(self):
        annotations = load_golden_annotations(self.golden_path)
        self.assertGreaterEqual(
            len(annotations),
            10,
            f"Need at least 10 golden documents, got {len(annotations)}",
        )

    def test_documents_cover_diverse_sources(self):
        annotations = load_golden_annotations(self.golden_path)
        sources = set(ann.get("source_type", "unknown") for ann in annotations.values())
        self.assertIn("rates", sources, "Need at least one rates document")

    def test_expected_outputs_have_required_fields(self):
        annotations = load_golden_annotations(self.golden_path)
        required_fields = [
            "thesis",
            "key_claims",
            "trading_opportunities",
            "talking_points",
        ]

        for doc_id, ann in annotations.items():
            expected = ann.get("expected", {})
            for field in required_fields:
                self.assertIn(
                    field, expected, f"{doc_id} missing expected field: {field}"
                )

    def test_key_claims_have_required_structure(self):
        annotations = load_golden_annotations(self.golden_path)

        for doc_id, ann in annotations.items():
            expected = ann.get("expected", {})
            claims = expected.get("key_claims", [])
            if claims:
                first_claim = claims[0]
                self.assertIn("claim", first_claim, f"{doc_id} claim missing 'claim'")
                self.assertIn(
                    "confidence", first_claim, f"{doc_id} claim missing 'confidence'"
                )

    def test_trading_opportunities_have_required_structure(self):
        annotations = load_golden_annotations(self.golden_path)

        for doc_id, ann in annotations.items():
            expected = ann.get("expected", {})
            trades = expected.get("trading_opportunities", [])
            if trades:
                first_trade = trades[0]
                self.assertIn("thesis", first_trade, f"{doc_id} trade missing 'thesis'")
                self.assertIn(
                    "direction", first_trade, f"{doc_id} trade missing 'direction'"
                )
                self.assertIn(
                    "instrument", first_trade, f"{doc_id} trade missing 'instrument'"
                )

    def test_all_document_files_exist(self):
        annotations = load_golden_annotations(self.golden_path)

        for doc_id, ann in annotations.items():
            doc_path = self.golden_path / ann["document_path"]
            self.assertTrue(
                doc_path.exists(), f"{doc_id}: document file not found: {doc_path}"
            )

    def test_confidence_scores_in_valid_range(self):
        annotations = load_golden_annotations(self.golden_path)

        for doc_id, ann in annotations.items():
            expected = ann.get("expected", {})

            for claim in expected.get("key_claims", []):
                conf = claim.get("confidence", 0)
                self.assertGreaterEqual(conf, 0.0, f"{doc_id}: confidence {conf} < 0")
                self.assertLessEqual(conf, 1.0, f"{doc_id}: confidence {conf} > 1")

    def test_some_annotations_include_argument_maps(self):
        annotations = load_golden_annotations(self.golden_path)
        mapped = [
            doc_id
            for doc_id, ann in annotations.items()
            if (ann.get("expected") or {}).get("argument_map")
        ]
        self.assertGreaterEqual(len(mapped), 2, "Need at least two labeled argument maps")

    def test_consensus_points_file_exists_and_has_both_kinds(self):
        path = self.golden_path / "consensus.jsonl"
        self.assertTrue(path.exists(), "consensus.jsonl must exist")
        kinds = set()
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                kinds.add(item.get("kind"))
        self.assertIn("consensus", kinds)
        self.assertIn("divergence", kinds)


if __name__ == "__main__":
    unittest.main()
