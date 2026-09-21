"""LLM Judge for evaluating agent outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_ARGUMENT_JUDGE_WEIGHTS: dict[str, float] = {
    "rationale_fidelity": 0.25,
    "substantive_vs_framing": 0.25,
    "groundedness": 0.25,
    "phantom_counterparty": 0.25,
}


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
        judge_model: str = "gpt-5-mini",
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


@dataclass
class ArgumentJudgeScore:
    """Structured score bundle from the argument-map / consensus judge."""

    rationale_fidelity: float
    substantive_vs_framing: float
    groundedness: float
    phantom_counterparty: float
    reasoning: str
    errors: list[str]
    weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_ARGUMENT_JUDGE_WEIGHTS)
    )

    @property
    def scores_dict(self) -> dict[str, float]:
        return {
            "rationale_fidelity": self.rationale_fidelity,
            "substantive_vs_framing": self.substantive_vs_framing,
            "groundedness": self.groundedness,
            "phantom_counterparty": self.phantom_counterparty,
        }

    @property
    def weighted_score(self) -> float:
        """Weighted mean of rubric dimensions. Not a pass/fail cutoff."""
        total_weight = 0.0
        weighted = 0.0
        scores = self.scores_dict
        for name, score in scores.items():
            weight = float(self.weights.get(name, 0.0))
            if weight <= 0:
                continue
            weighted += score * weight
            total_weight += weight
        if total_weight == 0:
            return 0.0
        return weighted / total_weight


def _item_as_dict(item: Any) -> dict[str, Any]:
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        return dump()
    return {"value": item}


class ArgumentJudge:
    """LLM judge for claims and consensus/divergence points.

    Distinct from `LLMJudge`, which scores final analyst output against a
    golden reference. This path uses `prompts/evals/argument_judge.md`.
    """

    def __init__(
        self,
        llm_client: Any,
        judge_model: str = "gpt-5-mini",
        prompt_path: Path | None = None,
        weights: dict[str, float] | None = None,
    ):
        self.llm_client = llm_client
        self.judge_model = judge_model
        self.weights = dict(weights or DEFAULT_ARGUMENT_JUDGE_WEIGHTS)

        if prompt_path is None:
            prompt_path = (
                Path(__file__).parent.parent.parent.parent
                / "prompts"
                / "evals"
                / "argument_judge.md"
            )
        self.prompt_path = Path(prompt_path)
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")
        return self._default_prompt()

    def _default_prompt(self) -> str:
        return """You are scoring argument-map claims and cross-author points.

## Kind
{{kind}}

## Item
{{item}}

## Source excerpt
{{source_document}}

Score 0-1: rationale_fidelity, substantive_vs_framing, groundedness, phantom_counterparty.
Return JSON with scores, reasoning, and errors."""

    def _format_prompt(self, kind: str, item: dict[str, Any], source_document: str) -> str:
        prompt = self._prompt_template
        prompt = prompt.replace("{{kind}}", kind)
        prompt = prompt.replace("{{item}}", json.dumps(item, indent=2, default=str))
        prompt = prompt.replace("{{source_document}}", source_document)
        return prompt

    def _parse_response(self, response: dict) -> ArgumentJudgeScore:
        scores = response.get("scores", {})
        reasoning = response.get("reasoning", "")
        errors = response.get("errors", [])
        if isinstance(errors, str):
            errors = [errors]
        return ArgumentJudgeScore(
            rationale_fidelity=float(scores.get("rationale_fidelity", 0.0)),
            substantive_vs_framing=float(scores.get("substantive_vs_framing", 0.0)),
            groundedness=float(scores.get("groundedness", 0.0)),
            phantom_counterparty=float(scores.get("phantom_counterparty", 0.0)),
            reasoning=reasoning,
            errors=errors,
            weights=dict(self.weights),
        )

    def _zero_score(self, reasoning: str, errors: list[str]) -> ArgumentJudgeScore:
        return ArgumentJudgeScore(
            rationale_fidelity=0.0,
            substantive_vs_framing=0.0,
            groundedness=0.0,
            phantom_counterparty=0.0,
            reasoning=reasoning,
            errors=errors,
            weights=dict(self.weights),
        )

    def evaluate(
        self,
        kind: str,
        item: Any,
        source_document: str = "",
    ) -> ArgumentJudgeScore:
        """Score one claim or consensus/divergence point."""
        payload_item = _item_as_dict(item)
        prompt = self._format_prompt(kind, payload_item, source_document)
        user_payload = {
            "kind": kind,
            "item": payload_item,
            "source_document": source_document,
        }
        try:
            response = self.llm_client.generate_structured(
                system_prompt=prompt,
                user_payload=user_payload,
                model=self.judge_model,
                timeout_seconds=60,
            )
            return self._parse_response(response)
        except Exception as e:
            return self._zero_score(
                f"Error: {type(e).__name__}: {e}",
                [str(e)],
            )

    def evaluate_claim(
        self,
        claim: Any,
        source_document: str = "",
    ) -> ArgumentJudgeScore:
        return self.evaluate("claim", claim, source_document)

    def evaluate_point(
        self,
        point: Any,
        source_document: str = "",
    ) -> ArgumentJudgeScore:
        return self.evaluate("point", point, source_document)
