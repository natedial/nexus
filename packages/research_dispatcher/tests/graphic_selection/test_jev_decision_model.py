"""Jev adapter tests with FakeJevTransport (no network)."""

from __future__ import annotations

import unittest

from src.graphic_selection.jev_decision_model import JevDecisionModel
from src.graphic_selection.jev_transport import FakeJevTransport, JevTransportError
from src.graphic_selection.models import DecisionBatch, DecisionUnit
from src.graphic_selection.question_set import (
    PATTERN_OPTIONS,
    REPRESENTATION_QUESTION_ID,
    build_questions_for_unit,
)


def _unit() -> DecisionUnit:
    return DecisionUnit(
        unit_id="u1",
        text="Headline scalars",
        data_shape="scalars",
        available_fields=["label", "value"],
    )


class JevDecisionModelTests(unittest.TestCase):
    def test_parses_choice_and_noul(self):
        unit = _unit()
        questions = build_questions_for_unit(unit)
        batch = DecisionBatch(batch_id="b1", units=[unit], questions=questions)

        answers = {}
        for question in questions:
            key = f"{question.target_unit_id}::{question.question_id}"
            if question.question_kind == "choice":
                probs = {opt: 0.0 for opt in PATTERN_OPTIONS}
                probs["metric_strip"] = 0.7
                remainder = 0.3 / (len(PATTERN_OPTIONS) - 1)
                for opt in PATTERN_OPTIONS:
                    if opt != "metric_strip":
                        probs[opt] = remainder
                answers[key] = {
                    "type": "choice",
                    "choice": "metric_strip",
                    "probabilities": probs,
                }
            else:
                yes = 0.9 if question.question_id == "has_scalar_levels" else 0.1
                answers[key] = {"type": "noul", "noul": yes}

        transport = FakeJevTransport(
            response_body={"model": "jev-1.13.0", "answers": answers}
        )
        model = JevDecisionModel(transport)
        result = model.classify_batch(batch)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.metadata.provider_name, "jev")
        by_qid = {r.question_id: r for r in result.results}
        self.assertEqual(
            by_qid[REPRESENTATION_QUESTION_ID].distribution.selected,
            "metric_strip",
        )
        self.assertEqual(by_qid["has_scalar_levels"].distribution.selected, "yes")
        self.assertTrue(transport.requests)
        # State must carry shape fields for Jev instructions.
        state_unit = transport.requests[0]["state"]["units"]["u1"]
        self.assertEqual(state_unit["data_shape"], "scalars")

    def test_transport_failure_is_failed_batch(self):
        unit = _unit()
        questions = build_questions_for_unit(unit)
        batch = DecisionBatch(batch_id="b1", units=[unit], questions=questions)
        transport = FakeJevTransport(
            error=JevTransportError("down", retryable=False)
        )
        result = JevDecisionModel(transport, max_retries=0).classify_batch(batch)
        self.assertEqual(result.status, "failed")
        self.assertIn("down", result.provider_error or "")


if __name__ == "__main__":
    unittest.main()
