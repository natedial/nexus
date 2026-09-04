"""Tests for eval database."""

import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.db import EvalDatabase, compute_golden_set_hash


class TestEvalDatabase(unittest.TestCase):
    """Tests for EvalDatabase class."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_eval.db"
        cls.db = EvalDatabase(cls.db_path)

    def test_database_created(self):
        self.assertTrue(self.db_path.exists())

    def test_insert_eval_run(self):
        import uuid

        run_id = f"test_run_{uuid.uuid4().hex[:8]}"

        self.db.insert_eval_run(
            run_id=run_id,
            document_id="doc_test",
            agent_type="synthesizer",
            schema_valid=True,
            field_scores={"thesis": 0.85, "key_claims_claim": 0.80},
            confidence=0.82,
            judge_scores={"thesis_clarity": 0.9},
            judge_reasoning="Good output",
            latency_ms=1500,
            model_used="gpt-5-mini",
            prompt_version="v1.0",
        )

        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"SELECT document_id, schema_valid, confidence FROM agent_eval_runs "
                f"WHERE run_id = '{run_id}'"
            )
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "doc_test")
            self.assertEqual(row[1], 1)
            self.assertEqual(row[2], 0.82)

    def test_save_baseline(self):
        metrics = {
            "schema_validity_rate": 0.95,
            "confidence_avg": 0.80,
            "latency_avg_ms": 2000,
        }

        self.db.save_baseline("v1.0_baseline", metrics, "abc123")

        loaded = self.db.load_baseline("v1.0_baseline")
        self.assertEqual(loaded, metrics)

    def test_load_baseline_not_found(self):
        loaded = self.db.load_baseline("nonexistent")
        self.assertIsNone(loaded)

    def test_list_baselines(self):
        metrics = {"confidence_avg": 0.75}
        self.db.save_baseline("test_baseline", metrics, "def456")

        baselines = self.db.list_baselines()
        self.assertGreater(len(baselines), 0)
        self.assertTrue(any(b["baseline_name"] == "test_baseline" for b in baselines))

    def test_insert_training_capture(self):
        import uuid

        cap_id = f"cap_{uuid.uuid4().hex[:8]}"

        self.db.insert_training_capture(
            capture_id=cap_id,
            document_id="doc_test",
            agent_type="synthesizer",
            confidence=0.85,
            quality_score=0.82,
            output_path="/path/to/output.json",
        )

        captures = self.db.get_training_captures(min_confidence=0.8)
        self.assertGreater(len(captures), 0)
        cap_ids = [c["capture_id"] for c in captures]
        self.assertIn(cap_id, cap_ids)

    def test_get_training_captures_filtered(self):
        self.db.insert_training_capture(
            "cap_002", "doc_002", "thesis", 0.65, None, None
        )
        self.db.insert_training_capture(
            "cap_003", "doc_003", "synthesizer", 0.90, None, None
        )

        captures = self.db.get_training_captures(min_confidence=0.75)
        for cap in captures:
            self.assertGreaterEqual(cap["confidence"], 0.75)

    def test_insert_alert(self):
        self.db.insert_alert(
            alert_type="regression",
            metric_name="confidence_avg",
            baseline_value=0.80,
            current_value=0.65,
            delta=-0.15,
            threshold=0.10,
        )

        alerts = self.db.get_unacknowledged_alerts()
        self.assertGreater(len(alerts), 0)
        self.assertEqual(alerts[0]["alert_type"], "regression")

    def test_acknowledge_alert(self):
        self.db.insert_alert(
            alert_type="regression",
            metric_name="test_metric",
            baseline_value=1.0,
            current_value=0.8,
            delta=-0.2,
            threshold=0.1,
        )

        alerts = self.db.get_unacknowledged_alerts()
        alert_id = alerts[0]["id"]

        self.db.acknowledge_alert(alert_id)

        alerts_after = self.db.get_unacknowledged_alerts()
        self.assertEqual(len(alerts_after), 0)


class TestComputeGoldenSetHash(unittest.TestCase):
    """Tests for golden set hash computation."""

    def test_hash_computation(self):
        temp_dir = tempfile.mkdtemp()
        golden_path = Path(temp_dir)

        annotations = [{"document_id": "doc_001", "expected": {"thesis": "test"}}]
        annotations_path = golden_path / "annotations.jsonl"
        import json

        with open(annotations_path, "w") as f:
            for ann in annotations:
                f.write(json.dumps(ann) + "\n")

        hash1 = compute_golden_set_hash(golden_path)
        self.assertIsInstance(hash1, str)
        self.assertEqual(len(hash1), 16)

        hash2 = compute_golden_set_hash(golden_path)
        self.assertEqual(hash1, hash2)

    def test_hash_empty_when_no_file(self):
        hash_val = compute_golden_set_hash(Path("/nonexistent"))
        self.assertEqual(hash_val, "")


if __name__ == "__main__":
    unittest.main()
