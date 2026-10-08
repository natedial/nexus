"""Tests for decision-model consistency and metamorphic families."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.decision_consistency import (
    CONTAMINATED_PREFIX,
    SEED_FORECAST,
    run_compound_decomposition,
    run_context_isolation,
    run_formatting_invariance,
    run_negative_recommendation_equivalence,
    run_repeatability,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.models.decision_models import (
    STATEMENT_TYPE_OPTIONS,
    AnswerDistribution,
    DecisionResult,
)
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel


def _choice_result(question, unit, selected: str) -> DecisionResult:
    remainder = (1.0 - 0.86) / (len(STATEMENT_TYPE_OPTIONS) - 1)
    probs = {
        option: (0.86 if option == selected else remainder)
        for option in STATEMENT_TYPE_OPTIONS
    }
    return DecisionResult(
        question_id=question.question_id,
        target_unit_id=question.target_unit_id,
        status="complete",
        distribution=AnswerDistribution(
            probabilities=probs,
            selected=selected,
            raw_probability=0.86,
        ),
        provider="fake",
        model_version="fake-1.0.0",
    )


def _recommend_sensitive(batch, question, unit):
    del batch
    if question.question_kind != "choice":
        return None
    text = unit.text.lower()
    selected = (
        "recommendation"
        if any(
            marker in text
            for marker in (
                "recommend",
                "reposition",
                "refrain",
                "hold current",
                "maintain the current",
                "do not initiate",
            )
        )
        else "assertion"
    )
    return _choice_result(question, unit, selected)


class ConsistencyFamilyTest(unittest.TestCase):
    def test_context_isolation_detects_contaminated_prefix_flip(self) -> None:
        model = FakeDecisionModel(responder=_recommend_sensitive)
        cases = run_context_isolation(model)
        prefix_case = next(
            case
            for case in cases
            if case.variant_text.startswith(CONTAMINATED_PREFIX)
        )
        self.assertTrue(prefix_case.choice_label_flip)
        self.assertTrue(prefix_case.failed)
        self.assertEqual(prefix_case.kind, "invariance")

    def test_context_isolation_stable_when_model_ignores_prefix(self) -> None:
        cases = run_context_isolation(FakeDecisionModel())
        self.assertTrue(cases)
        self.assertFalse(any(case.failed for case in cases))

    def test_negative_recommendation_variants_are_invariant_for_sensitive_model(self) -> None:
        cases = run_negative_recommendation_equivalence(
            FakeDecisionModel(responder=_recommend_sensitive)
        )
        self.assertTrue(cases)
        self.assertFalse(any(case.choice_label_flip for case in cases))

    def test_compound_decomposition_is_contrast_not_invariance(self) -> None:
        cases = run_compound_decomposition(FakeDecisionModel())
        self.assertTrue(cases)
        self.assertTrue(all(case.kind == "contrast" for case in cases))
        self.assertFalse(any(case.failed for case in cases))

    def test_formatting_invariance_holds_for_fake_provider(self) -> None:
        cases = run_formatting_invariance(FakeDecisionModel())
        self.assertTrue(cases)
        self.assertFalse(any(case.failed for case in cases))

    def test_repeatability_is_stable_for_fake_provider(self) -> None:
        draft = AssertionDraft(
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
            text=SEED_FORECAST,
            normalized_text=normalize_text(SEED_FORECAST),
            summary_text=SEED_FORECAST,
        )
        cases = run_repeatability(FakeDecisionModel(), [draft], runs=3)
        self.assertTrue(cases)
        self.assertFalse(any(case.failed for case in cases))


if __name__ == "__main__":
    unittest.main()
