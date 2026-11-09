"""Tests for high-precision decision-model silver labels."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_silver import (
    build_silver_record,
    evaluate_silver_agreement,
    silver_hits_for_unit,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel


def _draft(assertion_type: str, text: str) -> AssertionDraft:
    return AssertionDraft(
        chunk_order=1,
        assertion_order=1,
        assertion_type=assertion_type,
        text=text,
        normalized_text=normalize_text(text),
        summary_text=text,
    )


class SilverRuleTest(unittest.TestCase):
    def test_open_question_maps_to_question(self) -> None:
        hits = silver_hits_for_unit(
            text="How durable is shelter inflation?",
            assertion_type="open_question",
        )
        self.assertTrue(
            any(hit.field == "statement_type" and hit.value == "question" for hit in hits)
        )

    def test_trade_claim_maps_to_recommendation_and_action(self) -> None:
        record = build_silver_record(
            unit_id="u1",
            text="We recommend overweighting front-end Treasuries versus the long bond.",
            assertion_type="trade_claim",
        )
        self.assertEqual(record.included_labels["statement_type"], "recommendation")
        self.assertEqual(record.included_labels["is_trade_or_action"], True)

    def test_negative_status_quo_recommendation_language(self) -> None:
        record = build_silver_record(
            unit_id="u2",
            text="We see no compelling reason to reposition for major USD moves.",
            assertion_type="observation",
        )
        self.assertEqual(record.included_labels["statement_type"], "recommendation")
        self.assertEqual(record.included_labels["is_trade_or_action"], True)

    def test_quote_and_named_release_are_high_confidence_evidence(self) -> None:
        record = build_silver_record(
            unit_id="u3",
            text='According to the BLS employment report, "payrolls rose 142,000".',
            assertion_type="observation",
        )
        self.assertEqual(record.included_labels["contains_verifiable_evidence"], True)
        self.assertTrue(
            all(
                hit.confidence_tier == "high"
                for hit in record.hits
                if hit.field == "contains_verifiable_evidence"
            )
        )

    def test_bare_percent_is_low_confidence_and_excluded(self) -> None:
        record = build_silver_record(
            unit_id="u4",
            text="Inflation is still around 3%.",
            assertion_type="interpretation",
        )
        self.assertNotIn("contains_verifiable_evidence", record.included_labels)
        self.assertTrue(record.excluded_from_metrics)

    def test_methodology_boilerplate(self) -> None:
        record = build_silver_record(
            unit_id="u5",
            text="Please see the appendix for definitions of the variables used throughout this note.",
            assertion_type="observation",
        )
        self.assertEqual(record.included_labels["statement_type"], "background_methodology")

    def test_conflicting_statement_types_are_excluded(self) -> None:
        record = build_silver_record(
            unit_id="u6",
            text=(
                "We recommend holding duration. Please see the appendix for "
                "definitions of the variables used throughout this note."
            ),
            assertion_type="observation",
        )
        self.assertIn("explicit_recommendation_language", record.conflicting_rule_ids)
        self.assertIn("methodology_boilerplate", record.conflicting_rule_ids)
        self.assertNotIn("statement_type", record.included_labels)

    def test_silver_agreement_skips_model_abstention(self) -> None:
        artifact = ShadowDecisionClassifier(
            FakeDecisionModel(drop_question_ids={"statement_type"})
        ).classify_assertions([_draft("open_question", "How durable is cooling?")])
        report = evaluate_silver_agreement(artifact.units)
        self.assertEqual(report.compared, 0)
        self.assertTrue(any("abstentions" in note for note in report.notes))

    def test_silver_never_claims_to_be_gold(self) -> None:
        record = build_silver_record(
            unit_id="u7",
            text="How durable is the recent cooling in shelter inflation?",
            assertion_type="open_question",
        )
        report = evaluate_silver_agreement([])
        self.assertIn("never gold", " ".join(report.notes))
        self.assertEqual(record.included_labels["statement_type"], "question")


if __name__ == "__main__":
    unittest.main()
