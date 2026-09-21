"""Tests for the Slice 3 argument judge (distinct from the final-output judge)."""

from __future__ import annotations

import json
import re
import unittest
from difflib import SequenceMatcher
from pathlib import Path

from research_analysis_layer.config import Settings
from research_analysis_layer.evals.judge import (
    DEFAULT_ARGUMENT_JUDGE_WEIGHTS,
    ArgumentJudge,
    ArgumentJudgeScore,
    LLMJudge,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


class RubricStubClient:
    """Stub LLM that applies the argument-judge rubric heuristically."""

    def __init__(self) -> None:
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
        item = user_payload.get("item") or {}
        source = str(user_payload.get("source_document") or "")
        source_n = _normalize(source)
        rationale = str(item.get("rationale") or "")
        sides = item.get("sides") or []

        fidelity = 0.9
        if rationale and source_n and _normalize(rationale) not in source_n:
            fidelity = 0.15

        groundedness = 0.9
        for reason in item.get("reasons") or []:
            text = (
                str(reason.get("text") or "")
                if isinstance(reason, dict)
                else str(getattr(reason, "text", "") or "")
            )
            if source_n and text and _normalize(text) not in source_n:
                groundedness = 0.2

        substantive = 0.9
        claims = [
            str(side.get("claim") or "")
            if isinstance(side, dict)
            else str(getattr(side, "claim", "") or "")
            for side in sides
        ]
        if len(claims) >= 2:
            ratio = SequenceMatcher(
                None, _normalize(claims[0]), _normalize(claims[1])
            ).ratio()
            if ratio >= 0.55:
                substantive = 0.2

        blob = json.dumps(item) + " " + source
        phantom = 0.15 if re.search(
            r"some strategists|some analysts|the street disagrees",
            blob,
            re.I,
        ) else 0.9

        return {
            "scores": {
                "rationale_fidelity": fidelity,
                "substantive_vs_framing": substantive,
                "groundedness": groundedness,
                "phantom_counterparty": phantom,
            },
            "reasoning": "stub rubric",
            "errors": [],
        }


class TestArgumentJudge(unittest.TestCase):
    def test_uses_argument_judge_prompt_not_final_output_prompt(self) -> None:
        client = RubricStubClient()
        judge = ArgumentJudge(llm_client=client)
        self.assertTrue(str(judge.prompt_path).endswith("argument_judge.md"))
        self.assertIn("Rationale fidelity", judge._prompt_template)
        self.assertIn("Phantom counterparty", judge._prompt_template)
        self.assertNotIn("Thesis Clarity", judge._prompt_template)
        self.assertNotIn("Trading Actionability", judge._prompt_template)

        prompt_path = (
            Path(__file__).resolve().parents[2] / "prompts" / "evals" / "argument_judge.md"
        )
        self.assertTrue(prompt_path.is_file())
        self.assertEqual(judge.prompt_path.resolve(), prompt_path.resolve())

    def test_does_not_overload_final_output_judge(self) -> None:
        client = RubricStubClient()
        output_judge = LLMJudge(llm_client=client)
        argument_judge = ArgumentJudge(llm_client=client)
        self.assertNotEqual(output_judge.prompt_path, argument_judge.prompt_path)
        self.assertIn("Thesis Clarity", output_judge._prompt_template)

    def test_fabricated_rationale_scores_low_on_fidelity(self) -> None:
        client = RubricStubClient()
        judge = ArgumentJudge(llm_client=client)
        source = (
            "GS argues the Fed is done hiking because the December dots "
            "dropped the last projected hike."
        )
        score = judge.evaluate_claim(
            {
                "claim": "the Fed is done hiking",
                "rationale": (
                    "the author cited a secret BIS paper that never appears "
                    "in the note"
                ),
                "support_strength": "evidenced",
            },
            source_document=source,
        )
        self.assertLess(score.rationale_fidelity, 0.4)
        self.assertGreater(len(client.calls), 0)
        payload = client.calls[0]["user_payload"]
        self.assertEqual(payload["kind"], "claim")
        self.assertIn("secret BIS paper", json.dumps(payload["item"]))

    def test_faithful_rationale_scores_high_on_fidelity(self) -> None:
        client = RubricStubClient()
        judge = ArgumentJudge(llm_client=client)
        source = (
            "GS argues the Fed is done hiking because the December dots "
            "dropped the last projected hike."
        )
        score = judge.evaluate_claim(
            {
                "claim": "the Fed is done hiking",
                "rationale": (
                    "the December dots dropped the last projected hike"
                ),
            },
            source_document=source,
        )
        self.assertGreater(score.rationale_fidelity, 0.7)

    def test_reworded_disagreement_scores_low_on_substantive(self) -> None:
        client = RubricStubClient()
        judge = ArgumentJudge(llm_client=client)
        score = judge.evaluate_point(
            {
                "point": "timing of the first cut",
                "sides": [
                    {
                        "position": "Goldman Sachs",
                        "claim": "the first cut comes in the second half",
                        "polarity": "down",
                        "reasons": [
                            {
                                "text": "dots slipped to H2",
                                "ref_key": "span:gs-1",
                            }
                        ],
                    },
                    {
                        "position": "JPM",
                        "claim": "easing is delayed until the second half",
                        "polarity": "down",
                        "reasons": [
                            {
                                "text": "dots slipped to H2",
                                "ref_key": "span:jpm-1",
                            }
                        ],
                    },
                ],
                "verdict": "contested",
            },
            source_document="GS and JPM both write that the first cut is an H2 event.",
        )
        self.assertLess(score.substantive_vs_framing, 0.4)
        self.assertEqual(client.calls[0]["user_payload"]["kind"], "point")

    def test_opposing_polarities_score_high_on_substantive(self) -> None:
        client = RubricStubClient()
        judge = ArgumentJudge(llm_client=client)
        score = judge.evaluate_point(
            {
                "point": "timing of the first cut",
                "sides": [
                    {
                        "position": "Goldman Sachs",
                        "claim": "first cut in Q2 on the dot median",
                        "polarity": "down",
                    },
                    {
                        "position": "JPM",
                        "claim": "no cut this year while wages stay at 4.5%",
                        "polarity": "up",
                    },
                ],
            }
        )
        self.assertGreater(score.substantive_vs_framing, 0.7)

    def test_weighted_score_uses_config_weights_not_a_cutoff(self) -> None:
        score = ArgumentJudgeScore(
            rationale_fidelity=0.2,
            substantive_vs_framing=1.0,
            groundedness=1.0,
            phantom_counterparty=1.0,
            reasoning="test",
            errors=[],
            weights={
                "rationale_fidelity": 1.0,
                "substantive_vs_framing": 0.0,
                "groundedness": 0.0,
                "phantom_counterparty": 0.0,
            },
        )
        self.assertAlmostEqual(score.weighted_score, 0.2)
        self.assertFalse(hasattr(score, "passed"))
        self.assertEqual(
            set(DEFAULT_ARGUMENT_JUDGE_WEIGHTS),
            {
                "rationale_fidelity",
                "substantive_vs_framing",
                "groundedness",
                "phantom_counterparty",
            },
        )

    def test_settings_weights_are_env_configurable(self) -> None:
        import os
        from unittest.mock import patch

        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
            "RESEARCH_ANALYST_ARGUMENT_JUDGE_WEIGHT_RATIONALE_FIDELITY": "0.7",
            "RESEARCH_ANALYST_ARGUMENT_JUDGE_WEIGHT_SUBSTANTIVE": "0.1",
            "RESEARCH_ANALYST_ARGUMENT_JUDGE_WEIGHT_GROUNDEDNESS": "0.1",
            "RESEARCH_ANALYST_ARGUMENT_JUDGE_WEIGHT_PHANTOM": "0.1",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertAlmostEqual(settings.argument_judge_weights["rationale_fidelity"], 0.7)
        self.assertAlmostEqual(
            settings.argument_judge_weights["substantive_vs_framing"], 0.1
        )
        judge = ArgumentJudge(
            llm_client=RubricStubClient(),
            weights=settings.argument_judge_weights,
        )
        self.assertAlmostEqual(judge.weights["rationale_fidelity"], 0.7)

    def test_evaluate_error_returns_zero_bundle(self) -> None:
        class Boom:
            def generate_structured(self, **kwargs):
                raise RuntimeError("API error")

        judge = ArgumentJudge(llm_client=Boom())
        score = judge.evaluate_claim({"claim": "x", "rationale": "y"})
        self.assertEqual(score.rationale_fidelity, 0.0)
        self.assertIn("RuntimeError", score.reasoning)
        self.assertEqual(score.errors[0], "API error")


if __name__ == "__main__":
    unittest.main()
