"""Fake DecisionModel path exercises full question set."""

from __future__ import annotations

import unittest

from src.graphic_selection.fake_decision_model import FakeDecisionModel
from src.graphic_selection.models import DecisionBatch, DecisionUnit
from src.graphic_selection.question_set import (
    REPRESENTATION_QUESTION_ID,
    build_questions_for_unit,
)


class FakeDecisionModelTests(unittest.TestCase):
    def test_classify_batch_complete(self):
        unit = DecisionUnit(
            unit_id="u1",
            text="Signed category moves",
            data_shape="signed_changes",
            available_fields=["category", "signed_change", "unit", "common_domain"],
            eligibility={"has_signed_changes": True},
        )
        questions = build_questions_for_unit(unit)
        batch = DecisionBatch(batch_id="b1", units=[unit], questions=questions)
        result = FakeDecisionModel().classify_batch(batch)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.metadata.provider_name, "fake")
        by_qid = {r.question_id: r for r in result.results}
        choice = by_qid[REPRESENTATION_QUESTION_ID]
        self.assertEqual(choice.distribution.selected, "diverging_bars")
        self.assertEqual(by_qid["has_signed_changes"].distribution.selected, "yes")
        self.assertEqual(by_qid["has_scalar_levels"].distribution.selected, "no")

    def test_batch_error_fail_closed(self):
        unit = DecisionUnit(unit_id="u1", text="x", data_shape="none")
        questions = build_questions_for_unit(unit)
        batch = DecisionBatch(batch_id="b1", units=[unit], questions=questions)
        result = FakeDecisionModel(batch_error="boom").classify_batch(batch)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.provider_error, "boom")


if __name__ == "__main__":
    unittest.main()
