"""Tests for bounded decision-model review queue construction."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_metrics import GoldUnitLabel
from research_analysis_layer.evals.decision_review_queue import (
    ReviewCandidate,
    build_review_queue,
    review_packet_markdown,
    stored_input_diff,
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

    def test_agreed_document_gold_is_not_represented(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [_draft(1, "forecast", "We expect two cuts later this year.")],
            document_key="doc_002",
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                document_id="doc_002",
                statement_type="recommendation",
                noul_labels={"is_forecast": True, "is_trade_or_action": False},
            )
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=5)
        self.assertFalse(
            any(item.unit_id == "chunk-1:assertion-1" for item in queue)
        )

    def test_surrounding_context_uses_same_document_neighbors(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [
                _draft(1, "forecast", "We expect two cuts later this year."),
                _draft(2, "observation", "The desk published the usual disclaimer."),
            ],
            document_key="doc_ctx",
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(is_trade=True),
            )
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=5)
        first = next(item for item in queue if item.unit_id == "chunk-1:assertion-1")
        self.assertIsNotNone(first.surrounding_context)
        self.assertIn("The desk published the usual disclaimer.", first.surrounding_context or "")

    def test_queue_keeps_reviewed_text_when_stored_input_differs(self) -> None:
        text = "We expect two cuts later this year."
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [_draft(1, "forecast", text)]
        )
        gold = [
            GoldUnitLabel(
                unit_id="chunk-1:assertion-1",
                statement_type="recommendation",
                noul_labels=_noul(is_trade=True),
                reviewed_text="two cuts later this year",
                stored_model_input=text,
            )
        ]
        queue = build_review_queue(artifact.units, gold_labels=gold, packet_size=5)
        self.assertEqual(queue[0].reviewed_text, "two cuts later this year")
        self.assertEqual(queue[0].stored_model_input, text)

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
        self.assertLessEqual(
            sum(1 for line in packet.splitlines() if line.startswith("## ")), 20
        )
        self.assertIn("<details>", packet)
        self.assertIn("Surrounding context", packet)
        self.assertIn("Stored model input", packet)

    def test_packet_highlights_stored_input_prefix_diff(self) -> None:
        sentence = "The 2s10s spread should compress to 30bp."
        stored = "We recommend a flatter curve. " + sentence
        packet = review_packet_markdown(
            [
                ReviewCandidate(
                    unit_id="chunk-6:assertion-2",
                    document_id="doc_002",
                    source_text=stored,
                    priority=1,
                    reasons=["high_confidence_gold_disagreement"],
                    cluster_id="abc123abc123",
                    reviewed_text=sentence,
                    stored_model_input=stored,
                    surrounding_context="Previous: Front-end remains anchored.\n\nNext: Keep duration light.",
                    questions=["What is the primary statement type?"],
                )
            ]
        )
        self.assertIn(sentence, packet)
        self.assertIn("Extra prefix", packet)
        self.assertIn("We recommend a flatter curve.", packet)
        self.assertIn("Previous: Front-end remains anchored.", packet)
        self.assertNotIn(
            stored,
            packet.split("### Sentence", 1)[1].split("<details>", 1)[0],
        )

    def test_stored_input_diff_splits_contained_sentence(self) -> None:
        sentence = "Keep duration light into the print."
        stored = "Heading: " + sentence + " Trailing note."
        diff = stored_input_diff(sentence, stored)
        self.assertFalse(diff["identical"])
        self.assertEqual(diff["prefix"], "Heading: ")
        self.assertEqual(diff["suffix"], " Trailing note.")


if __name__ == "__main__":
    unittest.main()
