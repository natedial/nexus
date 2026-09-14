"""Tests for eval runner."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_analysis_layer.evals.runner import (
    AgentEvalRunner,
    EvalResult,
    EvalSummary,
    load_golden_annotations,
    load_golden_document,
    validate_schema,
)
from research_analysis_layer.evals.comparison import DEFAULT_FIELD_WEIGHTS


class MockLLMClient:
    """Mock LLM client for testing."""

    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"thesis": "Mock response", "confidence": 0.5}
        self.error = error
        self.calls: list[dict] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "model": model,
            }
        )
        if self.error:
            raise self.error
        return dict(self.response)


class TestValidateSchema(unittest.TestCase):
    """Tests for schema validation."""

    def test_valid_output(self):
        output = {"thesis": "Fed cuts delayed", "confidence": 0.8}
        self.assertTrue(validate_schema(output))

    def test_missing_thesis(self):
        output = {"confidence": 0.8}
        self.assertFalse(validate_schema(output))

    def test_missing_confidence(self):
        output = {"thesis": "Fed cuts delayed"}
        self.assertFalse(validate_schema(output))

    def test_invalid_confidence_type(self):
        output = {"thesis": "Fed cuts", "confidence": "high"}
        self.assertFalse(validate_schema(output))


class TestLoadGoldenAnnotations(unittest.TestCase):
    """Tests for loading golden annotations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.golden_path = Path(self.temp_dir)

        annotations = [
            {"document_id": "doc_001", "expected": {"thesis": "test 1"}},
            {"document_id": "doc_002", "expected": {"thesis": "test 2"}},
        ]
        annotations_path = self.golden_path / "annotations.jsonl"
        with open(annotations_path, "w") as f:
            for ann in annotations:
                f.write(json.dumps(ann) + "\n")

    def test_load_all(self):
        annotations = load_golden_annotations(self.golden_path)
        self.assertEqual(len(annotations), 2)
        self.assertIn("doc_001", annotations)
        self.assertIn("doc_002", annotations)

    def test_load_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            load_golden_annotations(Path("/nonexistent"))


class TestLoadGoldenDocument(unittest.TestCase):
    """Tests for loading golden documents."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.golden_path = Path(self.temp_dir)

        doc_content = "Sample document content"
        doc_path = self.golden_path / "documents" / "doc_001.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(doc_content)

        annotations = [
            {
                "document_id": "doc_001",
                "document_path": "documents/doc_001.md",
                "expected": {"thesis": "test thesis"},
                "source_type": "rates",
            }
        ]
        annotations_path = self.golden_path / "annotations.jsonl"
        with open(annotations_path, "w") as f:
            for ann in annotations:
                f.write(json.dumps(ann) + "\n")

    def test_load_document(self):
        doc = load_golden_document(self.golden_path, "doc_001")
        self.assertEqual(doc["document_id"], "doc_001")
        self.assertEqual(doc["content"], "Sample document content")
        self.assertEqual(doc["expected"]["thesis"], "test thesis")

    def test_load_missing_document(self):
        with self.assertRaises(ValueError):
            load_golden_document(self.golden_path, "doc_999")


class TestAgentEvalRunner(unittest.TestCase):
    """Tests for AgentEvalRunner."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.golden_path = Path(self.temp_dir) / "golden"
        self.output_dir = Path(self.temp_dir) / "output"
        self.golden_path.mkdir(parents=True)
        self.output_dir.mkdir(parents=True)

        doc_content = "Sample document about Fed policy"
        doc_path = self.golden_path / "documents" / "doc_001.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(doc_content)

        annotations = [
            {
                "document_id": "doc_001",
                "document_path": "documents/doc_001.md",
                "expected": {
                    "thesis": "Fed holds rates steady",
                    "key_claims": [{"claim": "Rates unchanged", "confidence": 0.9}],
                    "trading_opportunities": [],
                    "talking_points": [],
                    "confidence": 0.85,
                },
                "source_type": "rates",
            }
        ]
        annotations_path = self.golden_path / "annotations.jsonl"
        with open(annotations_path, "w") as f:
            for ann in annotations:
                f.write(json.dumps(ann) + "\n")

    def test_run_single_success(self):
        mock_client = MockLLMClient(
            response={
                "thesis": "Fed holds rates steady",
                "confidence": 0.85,
                "key_claims": [{"claim": "Rates unchanged", "confidence": 0.9}],
                "trading_opportunities": [],
                "talking_points": [],
            }
        )

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        result = runner.run_single("doc_001", agent_types=["synthesizer"])

        self.assertEqual(result.document_id, "doc_001")
        self.assertTrue(result.schema_valid)
        self.assertIsNone(result.error)
        self.assertGreater(result.confidence, 0.5)

    def test_run_single_with_error(self):
        mock_client = MockLLMClient(error=RuntimeError("API error"))

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        result = runner.run_single("doc_001", agent_types=["synthesizer"])

        self.assertIsNotNone(result.output.get("error"))
        self.assertIn("RuntimeError", result.output.get("thesis", ""))

    def test_run_golden(self):
        mock_client = MockLLMClient(
            response={
                "thesis": "Fed holds rates steady",
                "confidence": 0.85,
            }
        )

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        summary = runner.run_golden(limit=1)

        self.assertEqual(summary.total_docs, 1)
        self.assertGreater(summary.schema_validity_rate, 0)

    def test_save_results(self):
        mock_client = MockLLMClient()
        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        result = EvalResult(
            document_id="doc_001",
            agent_type="synthesizer",
            output={"thesis": "test"},
            expected={"thesis": "test"},
            schema_valid=True,
            field_scores={"thesis": 1.0},
            confidence=1.0,
            latency_ms=100,
        )

        summary = EvalSummary(
            total_docs=1,
            schema_validity_rate=1.0,
            field_scores={"thesis": 1.0},
            confidence_avg=1.0,
            latency_p95_ms=100,
            latency_avg_ms=100,
            results=[result],
        )

        output_path = runner.save_results(summary, run_id="test_run")
        self.assertTrue(output_path.exists())

        data = json.loads(output_path.read_text())
        self.assertEqual(data["run_id"], "test_run")
        self.assertEqual(data["total_docs"], 1)

    def test_compare_to_baseline_missing(self):
        mock_client = MockLLMClient()
        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        with self.assertRaises(FileNotFoundError):
            runner.compare_to_baseline(Path("/nonexistent/baseline.json"))

    def test_compare_to_baseline_string_error(self):
        mock_client = MockLLMClient()
        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
        )

        with self.assertRaises(ValueError) as ctx:
            runner.compare_to_baseline("my_baseline")

        self.assertIn("DB-backed baselines are not yet implemented", str(ctx.exception))


class TestSummarizeResults(unittest.TestCase):
    """Tests for result summarization."""

    def test_summarize_empty(self):
        mock_client = MockLLMClient()
        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=Path("/tmp"),
            output_dir=Path("/tmp"),
        )

        summary = runner._summarize_results([])

        self.assertEqual(summary.total_docs, 0)
        self.assertEqual(summary.schema_validity_rate, 0.0)

    def test_summarize_single_result(self):
        mock_client = MockLLMClient()
        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=Path("/tmp"),
            output_dir=Path("/tmp"),
        )

        results = [
            EvalResult(
                document_id="doc_001",
                agent_type="synthesizer",
                output={"thesis": "test", "confidence": 0.8},
                expected={"thesis": "test", "confidence": 0.8},
                schema_valid=True,
                field_scores={"thesis": 1.0},
                confidence=1.0,
                latency_ms=100,
            )
        ]

        summary = runner._summarize_results(results)

        self.assertEqual(summary.total_docs, 1)
        self.assertEqual(summary.schema_validity_rate, 1.0)
        self.assertEqual(summary.confidence_avg, 1.0)
        self.assertEqual(summary.latency_avg_ms, 100)


class MockAgentRegistry:
    """Mock AgentRegistry for testing."""

    def __init__(self, prompt: str | None = None, config: dict | None = None):
        self._prompt = prompt
        self._config = config or {
            "model": "gpt-5-mini",
            "timeout_seconds": 120,
        }

    def get_agent(self, name: str):
        from dataclasses import dataclass

        @dataclass
        class FakeConfig:
            model: str
            timeout_seconds: int

        return FakeConfig(**self._config) if self._config else None

    def load_prompt(self, name: str):
        return self._prompt


class TestRunAgentWiring(unittest.TestCase):
    """Tests for _run_agent wiring to real agents."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.golden_path = Path(self.temp_dir) / "golden"
        self.output_dir = Path(self.temp_dir) / "output"
        self.golden_path.mkdir(parents=True)
        self.output_dir.mkdir(parents=True)

        doc_content = """# Test Document

## Full Text Excerpt

This is test content about Fed policy.

## Themes

```json
[
  {"label": "Fed holds", "classification": "Forecast", "strength": "Primary", "context": "test"}
]
```

## Assertions

```json
[
  {"text": "Rates unchanged", "polarity": "neutral", "time_horizon": "months", "authority_band": "high"}
]
```
"""
        doc_path = self.golden_path / "documents" / "doc_001.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(doc_content)

        annotations = [
            {
                "document_id": "doc_001",
                "document_path": "documents/doc_001.md",
                "expected": {"thesis": "test thesis", "confidence": 0.8},
                "source_type": "rates",
            }
        ]
        annotations_path = self.golden_path / "annotations.jsonl"
        with open(annotations_path, "w") as f:
            for ann in annotations:
                f.write(json.dumps(ann) + "\n")

    def test_run_agent_uses_real_prompt(self):
        mock_client = MockLLMClient(
            response={"thesis": "Fed holds rates", "confidence": 0.8}
        )
        mock_registry = MockAgentRegistry(prompt="You are a synthesizer agent.")

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
            agent_registry=mock_registry,
        )

        result = runner._run_agent(
            "synthesizer", load_golden_document(self.golden_path, "doc_001")
        )

        self.assertEqual(len(mock_client.calls), 1)
        call = mock_client.calls[0]
        self.assertEqual(call["system_prompt"], "You are a synthesizer agent.")
        self.assertIn("document", call["user_payload"])

    def test_run_agent_payload_has_agent_type(self):
        mock_client = MockLLMClient(
            response={"thesis": "Fed holds rates", "confidence": 0.8}
        )
        mock_registry = MockAgentRegistry(prompt="Test prompt")

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
            agent_registry=mock_registry,
        )

        result = runner._run_agent(
            "synthesizer", load_golden_document(self.golden_path, "doc_001")
        )

        call = mock_client.calls[0]
        payload = call["user_payload"]
        self.assertEqual(payload.get("agent_type"), "synthesizer")

    def test_run_agent_payload_has_document_fields(self):
        mock_client = MockLLMClient(
            response={"thesis": "Fed holds rates", "confidence": 0.8}
        )
        mock_registry = MockAgentRegistry(prompt="Test prompt")

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
            agent_registry=mock_registry,
        )

        result = runner._run_agent(
            "synthesizer", load_golden_document(self.golden_path, "doc_001")
        )

        call = mock_client.calls[0]
        payload = call["user_payload"]
        doc = payload.get("document", {})
        self.assertIn("full_text_excerpt", doc)
        self.assertEqual(doc.get("document_name"), "doc_001")
        self.assertEqual(doc.get("source"), "rates")

    def test_run_agent_payload_has_assertions(self):
        mock_client = MockLLMClient(
            response={"thesis": "Fed holds rates", "confidence": 0.8}
        )
        mock_registry = MockAgentRegistry(prompt="Test prompt")

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
            agent_registry=mock_registry,
        )

        result = runner._run_agent(
            "synthesizer", load_golden_document(self.golden_path, "doc_001")
        )

        call = mock_client.calls[0]
        payload = call["user_payload"]
        det_analysis = payload.get("deterministic_analysis", {})
        self.assertIn("assertions", det_analysis)
        self.assertTrue(len(det_analysis["assertions"]) > 0)

    def test_run_agent_uses_config_model(self):
        mock_client = MockLLMClient(
            response={"thesis": "Fed holds rates", "confidence": 0.8}
        )
        mock_registry = MockAgentRegistry(
            prompt="Test prompt",
            config={"model": "gpt-5-mini", "timeout_seconds": 60},
        )

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=self.golden_path,
            output_dir=self.output_dir,
            agent_registry=mock_registry,
        )

        result = runner._run_agent(
            "synthesizer", load_golden_document(self.golden_path, "doc_001")
        )

        call = mock_client.calls[0]
        self.assertEqual(call["model"], "gpt-5-mini")


if __name__ == "__main__":
    unittest.main()
