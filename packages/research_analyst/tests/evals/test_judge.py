"""Tests for LLM Judge."""

import unittest
from pathlib import Path
from dataclasses import dataclass

from research_analysis_layer.evals.judge import LLMJudge, JudgeScore


class MockJudgeLLMClient:
    """Mock LLM client for judge testing."""

    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {
            "scores": {
                "thesis_clarity": 0.85,
                "claim_grounding": 0.80,
                "trading_actionability": 0.75,
                "talking_point_quality": 0.90,
                "coherence": 0.88,
            },
            "reasoning": "Good output overall",
            "errors": [],
        }
        self.error = error
        self.calls: list[dict] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str,
        timeout_seconds: int,
    ) -> dict:
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


class TestJudgeScore(unittest.TestCase):
    """Tests for JudgeScore dataclass."""

    def test_scores_dict(self):
        score = JudgeScore(
            thesis_clarity=0.8,
            claim_grounding=0.7,
            trading_actionability=0.6,
            talking_point_quality=0.9,
            coherence=0.85,
            reasoning="Test",
            errors=[],
        )
        expected = {
            "thesis_clarity": 0.8,
            "claim_grounding": 0.7,
            "trading_actionability": 0.6,
            "talking_point_quality": 0.9,
            "coherence": 0.85,
        }
        self.assertEqual(score.scores_dict, expected)

    def test_average(self):
        score = JudgeScore(
            thesis_clarity=0.8,
            claim_grounding=0.7,
            trading_actionability=0.6,
            talking_point_quality=0.9,
            coherence=0.85,
            reasoning="Test",
            errors=[],
        )
        expected_avg = (0.8 + 0.7 + 0.6 + 0.9 + 0.85) / 5
        self.assertAlmostEqual(score.average, expected_avg)


class TestLLMJudge(unittest.TestCase):
    """Tests for LLMJudge class."""

    def test_judge_initialization(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(
            llm_client=mock_client,
            judge_model="gpt-5-mini",
        )
        self.assertEqual(judge.judge_model, "gpt-5-mini")

    def test_judge_loads_prompt(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)
        self.assertIn("You are evaluating", judge._prompt_template)

    def test_format_prompt(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        agent_output = {"thesis": "Test thesis", "confidence": 0.8}
        golden_output = {"thesis": "Golden thesis", "confidence": 0.9}
        source_document = "Fed held rates steady citing persistent inflation."

        formatted = judge._format_prompt(agent_output, golden_output, source_document)

        self.assertIn("Test thesis", formatted)
        self.assertIn("Golden thesis", formatted)
        self.assertIn("Fed held rates steady", formatted)

    def test_format_prompt_without_source(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        agent_output = {"thesis": "Test thesis", "confidence": 0.8}
        golden_output = {"thesis": "Golden thesis", "confidence": 0.9}

        # source_document defaults to empty string — {{source_document}} replaced with ""
        formatted = judge._format_prompt(agent_output, golden_output)
        self.assertNotIn("{{source_document}}", formatted)

    def test_parse_response(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        response = {
            "scores": {
                "thesis_clarity": 0.85,
                "claim_grounding": 0.80,
                "trading_actionability": 0.75,
                "talking_point_quality": 0.90,
                "coherence": 0.88,
            },
            "reasoning": "Good output",
            "errors": ["Minor issue"],
        }

        score = judge._parse_response(response)

        self.assertEqual(score.thesis_clarity, 0.85)
        self.assertEqual(score.claim_grounding, 0.80)
        self.assertEqual(score.trading_actionability, 0.75)
        self.assertEqual(score.talking_point_quality, 0.90)
        self.assertEqual(score.coherence, 0.88)
        self.assertEqual(score.reasoning, "Good output")
        self.assertEqual(score.errors, ["Minor issue"])

    def test_evaluate_success(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        agent_output = {"thesis": "Test thesis", "confidence": 0.8}
        golden_output = {"thesis": "Golden thesis", "confidence": 0.9}
        source_document = "Fed held rates steady citing persistent inflation."

        score = judge.evaluate(agent_output, golden_output, source_document)

        self.assertEqual(score.thesis_clarity, 0.85)
        self.assertGreater(len(mock_client.calls), 0)
        # Verify source document was included in the prompt
        self.assertIn("Fed held rates steady", mock_client.calls[0]["system_prompt"])

    def test_evaluate_error(self):
        mock_client = MockJudgeLLMClient(error=RuntimeError("API error"))
        judge = LLMJudge(llm_client=mock_client)

        agent_output = {"thesis": "Test", "confidence": 0.8}
        golden_output = {"thesis": "Golden", "confidence": 0.9}

        score = judge.evaluate(agent_output, golden_output)

        self.assertEqual(score.thesis_clarity, 0.0)
        self.assertIn("RuntimeError", score.reasoning)
        self.assertEqual(score.errors[0], "API error")

    def test_evaluate_batch(self):
        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        evaluations = [
            (
                {"thesis": "Test 1", "confidence": 0.8},
                {"thesis": "Golden 1", "confidence": 0.9},
                "Source document 1",
            ),
            (
                {"thesis": "Test 2", "confidence": 0.7},
                {"thesis": "Golden 2", "confidence": 0.85},
                "Source document 2",
            ),
        ]

        scores = judge.evaluate_batch(evaluations)

        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[0].thesis_clarity, 0.85)
        self.assertEqual(scores[1].thesis_clarity, 0.85)


class TestJudgeWithRunner(unittest.TestCase):
    """Tests for judge integration with runner."""

    def test_runner_accepts_llm_judge(self):
        from research_analysis_layer.evals.runner import AgentEvalRunner

        mock_client = MockJudgeLLMClient()
        judge = LLMJudge(llm_client=mock_client)

        runner = AgentEvalRunner(
            llm_client=mock_client,
            golden_path=Path("evals/golden"),
            output_dir=Path("evals/results"),
            llm_judge=judge,
        )

        self.assertIs(runner.llm_judge, judge)


if __name__ == "__main__":
    unittest.main()
