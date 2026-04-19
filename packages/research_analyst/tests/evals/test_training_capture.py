"""Tests for training capture."""

import json
import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.training_capture import (
    CAPTURE_THRESHOLD,
    TrainingCapture,
    TrainingCaptureManager,
)


class TestTrainingCaptureManager(unittest.TestCase):
    """Tests for TrainingCaptureManager class."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.captures_dir = Path(cls.temp_dir) / "captures"
        cls.manager = TrainingCaptureManager(
            captures_dir=cls.captures_dir,
            min_confidence=0.75,
        )

    def test_should_capture_meets_threshold(self):
        self.assertTrue(self.manager.should_capture(0.80, True))
        self.assertTrue(self.manager.should_capture(0.75, True))
        self.assertTrue(self.manager.should_capture(1.0, True))

    def test_should_capture_below_threshold(self):
        self.assertFalse(self.manager.should_capture(0.74, True))
        self.assertFalse(self.manager.should_capture(0.50, True))

    def test_should_capture_invalid_schema(self):
        self.assertFalse(self.manager.should_capture(0.90, False))
        self.assertFalse(self.manager.should_capture(0.80, False))

    def test_capture_meets_criteria(self):
        capture = self.manager.capture(
            document_id="doc_001",
            input_data={"content": "test input"},
            output_data={"thesis": "test thesis", "confidence": 0.85},
            metadata={
                "agent_type": "synthesizer",
                "model": "claude-sonnet",
                "confidence": 0.85,
                "schema_valid": True,
                "latency_ms": 1000,
            },
            quality={"judge_score": 0.80},
        )

        self.assertIsNotNone(capture)
        self.assertIsNotNone(capture.capture_id)
        self.assertEqual(capture.document_id, "doc_001")
        self.assertIn("test thesis", capture.output["thesis"])

    def test_capture_below_threshold(self):
        capture = self.manager.capture(
            document_id="doc_002",
            input_data={"content": "test"},
            output_data={"thesis": "test", "confidence": 0.5},
            metadata={
                "agent_type": "synthesizer",
                "confidence": 0.5,
                "schema_valid": True,
            },
        )

        self.assertIsNone(capture)

    def test_capture_creates_index(self):
        self.manager.capture(
            document_id="doc_003",
            input_data={"content": "test"},
            output_data={"thesis": "test", "confidence": 0.9},
            metadata={
                "agent_type": "synthesizer",
                "confidence": 0.9,
                "schema_valid": True,
            },
        )

        index_path = self.captures_dir / "index.jsonl"
        self.assertTrue(index_path.exists())

        with open(index_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        self.assertGreater(len(entries), 0)

    def test_export(self):
        for i in range(3):
            self.manager.capture(
                document_id=f"doc_{i:03d}",
                input_data={"content": f"test {i}"},
                output_data={"thesis": f"thesis {i}", "confidence": 0.80 + i * 0.05},
                metadata={
                    "agent_type": "synthesizer",
                    "confidence": 0.80 + i * 0.05,
                    "schema_valid": True,
                },
            )

        output_path = Path(self.temp_dir) / "export.jsonl"
        count = self.manager.export(
            output_path=output_path,
            min_confidence=0.80,
        )

        self.assertGreater(count, 0)
        self.assertTrue(output_path.exists())

        with open(output_path) as f:
            exports = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(exports), count)

    def test_export_with_date_filter(self):
        capture = self.manager.capture(
            document_id="doc_dated",
            input_data={"content": "test"},
            output_data={"thesis": "test", "confidence": 0.85},
            metadata={
                "agent_type": "synthesizer",
                "confidence": 0.85,
                "schema_valid": True,
            },
        )

        output_path = Path(self.temp_dir) / "export_filtered.jsonl"

        count = self.manager.export(
            output_path=output_path,
            min_confidence=0.75,
            start_date="2030-01-01",
        )

        self.assertEqual(count, 0)

    def test_get_capture_count(self):
        count_before = self.manager.get_capture_count()

        self.manager.capture(
            document_id="doc_new",
            input_data={"content": "test"},
            output_data={"thesis": "test", "confidence": 0.85},
            metadata={
                "agent_type": "synthesizer",
                "confidence": 0.85,
                "schema_valid": True,
            },
        )

        count_after = self.manager.get_capture_count()
        self.assertEqual(count_after, count_before + 1)


class TestCaptureThreshold(unittest.TestCase):
    """Tests for capture threshold constant."""

    def test_threshold_value(self):
        self.assertEqual(CAPTURE_THRESHOLD, 0.75)


class TestTrainingCapture(unittest.TestCase):
    """Tests for TrainingCapture dataclass."""

    def test_capture_creation(self):
        capture = TrainingCapture(
            capture_id="test_cap_001",
            document_id="doc_001",
            capture_timestamp="2026-04-14T10:00:00Z",
            input={"content": "test"},
            output={"thesis": "test"},
            metadata={"model": "claude-sonnet"},
            quality={"judge_score": 0.85},
        )

        self.assertEqual(capture.capture_id, "test_cap_001")
        self.assertEqual(capture.document_id, "doc_001")
        self.assertEqual(capture.quality["judge_score"], 0.85)


def test_capture_request_writes_input_output_and_metadata(tmp_path: Path):
    from research_analysis_layer.evals.trigger import CaptureRequest

    manager = TrainingCaptureManager(captures_dir=tmp_path, min_confidence=0.5)
    request = CaptureRequest(
        document_id="doc-xyz",
        analysis_version="bootstrap-v1",
        agent_type="synthesizer",
        input_payload={"document": {"research_id": 7}},
        output_payload={"thesis": "Strong long EUR", "confidence": 0.82},
        metadata={
            "model_used": "gpt-5-mini",
            "run_id": 42,
            "debate_session_id": "debate:7:hash:bootstrap-v1:42",
            "schema_valid": True,
        },
        confidence=0.82,
        quality_signals={"forum_accepted_thesis": True},
    )

    capture = manager.capture_request(request)

    assert capture is not None
    payload = json.loads(Path(manager._capture_path(capture.capture_id)).read_text())
    assert payload["input"]["document"]["research_id"] == 7
    assert payload["output"]["thesis"] == "Strong long EUR"
    assert payload["metadata"]["debate_session_id"].startswith("debate:")
    assert payload["quality"]["forum_accepted_thesis"] is True


def test_capture_request_dedupes_on_document_and_version(tmp_path: Path):
    from research_analysis_layer.evals.trigger import CaptureRequest

    manager = TrainingCaptureManager(captures_dir=tmp_path, min_confidence=0.5)
    base = CaptureRequest(
        document_id="doc-1",
        analysis_version="v1",
        agent_type="synthesizer",
        input_payload={},
        output_payload={"thesis": "x", "confidence": 0.9},
        metadata={"schema_valid": True},
        confidence=0.9,
    )
    first = manager.capture_request(base)
    second = manager.capture_request(base)
    assert first is not None
    assert second is None


if __name__ == "__main__":
    unittest.main()
