"""LLM Judge for evaluating agent outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class JudgeScore:
    """Score from LLM judge."""

    thesis_clarity: float
    claim_grounding: float
    trading_actionability: float
    talking_point_quality: float
    coherence: float
    reasoning: str
    errors: list[str]

    @property
    def scores_dict(self) -> dict[str, float]:
        return {
            "thesis_clarity": self.thesis_clarity,
            "claim_grounding": self.claim_grounding,
            "trading_actionability": self.trading_actionability,
            "talking_point_quality": self.talking_point_quality,
            "coherence": self.coherence,
        }

    @property
    def average(self) -> float:
        return sum(self.scores_dict.values()) / len(self.scores_dict)


class LLMJudge:
    """LLM-based judge for evaluating agent outputs.

    Uses a separate LLM to evaluate agent outputs against golden references.
    """

    def __init__(
        self,
        llm_client: Any,
        judge_model: str = "claude-haiku-4-5-20251001",
        prompt_path: Path | None = None,
    ):
        """Initialize judge.

        Args:
            llm_client: LLM client for making evaluation calls
            judge_model: Model to use for judge
            prompt_path: Path to judge prompt (default: prompts/evals/judge.md)
        """
        self.llm_client = llm_client
        self.judge_model = judge_model

        if prompt_path is None:
            prompt_path = (
                Path(__file__).parent.parent.parent.parent
                / "prompts"
                / "evals"
                / "judge.md"
            )

        self.prompt_path = Path(prompt_path)
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load judge prompt from file."""
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return self._default_prompt()

    def _default_prompt(self) -> str:
        """Default prompt if file not found."""
        return """You are evaluating the output of an AI research analyst agent.

## Task
Compare the agent's output to the golden reference and score quality.

## Agent Output
{{agent_output}}

## Golden Reference
{{golden_output}}

## Scoring Rubric (score 0-1 each)
1. Thesis Clarity (0-1)
2. Claim Grounding (0-1)
3. Trading Actionability (0-1)
4. Talking Point Quality (0-1)
5. Coherence (0-1)

Return JSON with scores and reasoning."""

    def _format_prompt(
        self,
        agent_output: dict,
        golden_output: dict,
        source_document: str = "",
    ) -> str:
        """Format prompt with variables replaced."""
        prompt = self._prompt_template
        prompt = prompt.replace("{{source_document}}", source_document)
        prompt = prompt.replace("{{agent_output}}", json.dumps(agent_output, indent=2))
        prompt = prompt.replace(
            "{{golden_output}}", json.dumps(golden_output, indent=2)
        )
        return prompt

    def _parse_response(self, response: dict) -> JudgeScore:
        """Parse LLM response into JudgeScore."""
        scores = response.get("scores", {})
        reasoning = response.get("reasoning", "")
        errors = response.get("errors", [])

        if isinstance(errors, str):
            errors = [errors]

        return JudgeScore(
            thesis_clarity=float(scores.get("thesis_clarity", 0.0)),
            claim_grounding=float(scores.get("claim_grounding", 0.0)),
            trading_actionability=float(scores.get("trading_actionability", 0.0)),
            talking_point_quality=float(scores.get("talking_point_quality", 0.0)),
            coherence=float(scores.get("coherence", 0.0)),
            reasoning=reasoning,
            errors=errors,
        )

    def evaluate(
        self,
        agent_output: dict,
        golden_output: dict,
        source_document: str = "",
    ) -> JudgeScore:
        """Evaluate agent output against golden reference.

        Args:
            agent_output: The actual output from the agent
            golden_output: The expected/golden output
            source_document: The source document text, used to verify claim grounding
                             directly against the source rather than just the golden reference

        Returns:
            JudgeScore with scores for each dimension
        """
        prompt = self._format_prompt(agent_output, golden_output, source_document)

        try:
            response = self.llm_client.generate_structured(
                system_prompt=prompt,
                user_payload={},
                model=self.judge_model,
                timeout_seconds=60,
            )
            return self._parse_response(response)
        except Exception as e:
            return JudgeScore(
                thesis_clarity=0.0,
                claim_grounding=0.0,
                trading_actionability=0.0,
                talking_point_quality=0.0,
                coherence=0.0,
                reasoning=f"Error: {type(e).__name__}: {e}",
                errors=[str(e)],
            )

    def evaluate_batch(
        self,
        evaluations: list[tuple[dict, dict, str]],
    ) -> list[JudgeScore]:
        """Evaluate multiple outputs in batch.

        Args:
            evaluations: List of (agent_output, golden_output, source_document) tuples

        Returns:
            List of JudgeScore for each evaluation
        """
        results = []
        for agent_output, golden_output, source_document in evaluations:
            score = self.evaluate(agent_output, golden_output, source_document)
            results.append(score)
        return results
