"""Tests for decision-model consistency and metamorphic families."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.decision_consistency import (
    CONTAMINATED_PREFIX,
    SEED_FORECAST,
    run_batch_invariance,
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

    def test_batch_invariance_holds_for_fake_provider(self) -> None:
        drafts = [
            AssertionDraft(
                chunk_order=1,
                assertion_order=1,
                assertion_type="forecast",
                text=SEED_FORECAST,
                normalized_text=normalize_text(SEED_FORECAST),
                summary_text=SEED_FORECAST,
            ),
            AssertionDraft(
                chunk_order=1,
                assertion_order=2,
                assertion_type="observation",
                text="Payrolls printed 180k last month.",
                normalized_text=normalize_text("Payrolls printed 180k last month."),
                summary_text="Payrolls printed 180k last month.",
            ),
        ]
        cases = run_batch_invariance(FakeDecisionModel(), drafts)
        case_ids = {case.case_id for case in cases}
        self.assertTrue(any(item.startswith("batch-size-") for item in case_ids))
        self.assertTrue(any(item.startswith("batch-order-") for item in case_ids))
        self.assertTrue(any(item.startswith("batch-neighbor-") for item in case_ids))
        self.assertFalse(any(case.failed for case in cases))

    def test_batch_neighbor_flip_is_a_failure(self) -> None:
        def neighbor_sensitive(batch, question, unit):
            if question.question_kind != "choice":
                return None
            if SEED_FORECAST not in unit.text:
                return None
            if any(
                "recommend" in other.text.lower()
                for other in batch.units
                if other.unit_id != unit.unit_id
            ):
                return _choice_result(question, unit, "recommendation")
            return _choice_result(question, unit, "assertion")

        drafts = [
            AssertionDraft(
                chunk_order=1,
                assertion_order=1,
                assertion_type="forecast",
                text=SEED_FORECAST,
                normalized_text=normalize_text(SEED_FORECAST),
                summary_text=SEED_FORECAST,
            )
        ]
        cases = run_batch_invariance(
            FakeDecisionModel(responder=neighbor_sensitive), drafts
        )
        neighbor_cases = [
            case for case in cases if case.case_id.startswith("batch-neighbor-")
        ]
        self.assertTrue(neighbor_cases)
        self.assertTrue(all(case.choice_label_flip and case.failed for case in neighbor_cases))

    def test_batch_order_flip_is_a_failure(self) -> None:
        def order_sensitive(batch, question, unit):
            if question.question_kind != "choice":
                return None
            selected = (
                "assertion"
                if batch.units and batch.units[0].unit_id == unit.unit_id
                else "recommendation"
            )
            return _choice_result(question, unit, selected)

        drafts = [
            AssertionDraft(
                chunk_order=1,
                assertion_order=index,
                assertion_type="forecast",
                text=f"We expect cut number {index} later this year.",
                normalized_text=normalize_text(f"We expect cut number {index} later this year."),
                summary_text=f"We expect cut number {index} later this year.",
            )
            for index in (1, 2)
        ]
        cases = run_batch_invariance(
            FakeDecisionModel(responder=order_sensitive), drafts
        )
        order_cases = [
            case for case in cases if case.case_id.startswith("batch-order-")
        ]
        self.assertTrue(order_cases)
        self.assertTrue(any(case.choice_label_flip and case.failed for case in order_cases))

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
