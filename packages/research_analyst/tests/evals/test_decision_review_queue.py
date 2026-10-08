"""Tests for bounded decision-model review queue construction."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_metrics import GoldUnitLabel
from research_analysis_layer.evals.decision_review_queue import (
    build_review_queue,
    review_packet_markdown,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel


def _draft(order: int, assertion_type: str, text: str) -> AssertionDraft:
    return AssertionDraft(
        chunk_order=1,
        assertion_order=order,
        assertion_type=assertion_type,
        text=text,
        normalized_text=normalize_text(text),
        summary_text=text,
    )


def _noul(is_forecast: bool = False, is_trade: bool = False) -> dict[str, bool]:
    return {
        "is_observation": False,
        "is_forecast": is_forecast,
        "is_causal": False,
        "is_market_impact": False,
        "is_policy_claim": False,
        "is_risk_or_scenario": False,
        "is_comparative": False,
        "is_trade_or_action": is_trade,
        "contains_verifiable_evidence": False,
        "contains_reasoning_bridge": False,
        "is_substantive_author_claim": True,
    }


class ReviewQueueTest(unittest.TestCase):
    def test_high_confidence_gold_disagreement_outranks_random_audit(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [
                _draft(1, "forecast", "We expect two cuts later this year."),
                _draft(2, "observation", "The desk published the usual disclaimer."),
            ]
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(is_trade=True),
            )
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=5)
        self.assertLessEqual(len(queue), 5)
        self.assertEqual(queue[0].unit_id, "chunk-1:assertion-1")
        self.assertIn("high_confidence_gold_disagreement", queue[0].reasons)
        self.assertTrue(any(item.priority == 7 for item in queue))

    def test_near_duplicates_are_clustered(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [
                _draft(1, "forecast", "We expect the Fed to cut rates next quarter."),
                _draft(2, "forecast", "We expect the Fed to cut rates next quarter!"),
            ]
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(),
            ),
            GoldUnitLabel(
                unit_id="chunk-1:assertion-2",
                statement_type="recommendation",
                noul_labels=_noul(),
            ),
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=20)
        self.assertEqual(len(queue), 1)

    def test_fixture_gold_does_not_attach_to_other_documents(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [_draft(1, "forecast", "We expect two cuts later this year.")],
            document_key="doc_004",
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(is_trade=True),
            )
        ]
        queue = build_review_queue(
            artifact.units,
            gold_labels=gold,
            gold_document_id="decision-shadow-fixture-v2",
            packet_size=5,
        )
        self.assertFalse(
            any("high_confidence_gold_disagreement" in item.reasons for item in queue)
        )

    def test_packet_markdown_marks_suggestions_as_proposals(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [_draft(1, "forecast", "We expect two cuts later this year.")]
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(is_trade=True),
            )
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=5)
        packet = review_packet_markdown(queue)
        self.assertIn("suggestions only", packet.lower())
        self.assertIn("agent proposal", packet.lower())
        self.assertLessEqual(packet.count("## "), 20)


if __name__ == "__main__":
    unittest.main()
