"""Tests for provider-neutral shadow decision classification (PR1)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.decision_artifacts import (
    load_shadow_artifact,
    write_question_set_snapshot,
    write_shadow_artifact,
)
from research_analysis_layer.evals.decision_baseline import (
    map_choice_baseline,
    map_subtype_baseline,
)
from research_analysis_layer.evals.decision_classifier import (
    ShadowDecisionClassifier,
    assertion_unit_id,
)
from research_analysis_layer.evals.decision_fixture import (
    fixture_assertions,
    fixture_dir,
    fixture_provenance,
    fixture_section_context,
    load_fixture_labels,
)
from research_analysis_layer.evals.decision_metrics import evaluate_shadow_artifact
from research_analysis_layer.evals.decision_question_set import (
    build_questions_for_unit,
    expected_question_ids,
    snapshot_question_set,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.models.decision_models import (
    ARTIFACT_SCHEMA_VERSION,
    QUESTION_SET_VERSION,
    STATEMENT_TYPE_OPTIONS,
    AnswerDistribution,
    DecisionBatch,
    DecisionQuestion,
    DecisionUnit,
)
from research_analysis_layer.services.fake_decision_model import (
    FakeDecisionModel,
    scripted_result,
)


def _draft(
    chunk_order: int,
    assertion_order: int,
    assertion_type: str,
    text: str,
) -> AssertionDraft:
    return AssertionDraft(
        chunk_order=chunk_order,
        assertion_order=assertion_order,
        assertion_type=assertion_type,
        text=text,
        normalized_text=normalize_text(text),
        summary_text=text,
    )


class DecisionContractTest(unittest.TestCase):
    def test_answer_distribution_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            AnswerDistribution(probabilities={"yes": 1.2, "no": -0.2})

    def test_answer_distribution_rejects_non_unit_mass(self) -> None:
        with self.assertRaises(ValueError):
            AnswerDistribution(probabilities={"a": 0.4, "b": 0.4})

    def test_choice_question_requires_options(self) -> None:
        with self.assertRaises(ValueError):
            DecisionQuestion(
                question_id="statement_type",
                target_unit_id="chunk-1:assertion-1",
                question_kind="choice",
                wording="pick one",
            )

    def test_question_set_covers_v1_axes(self) -> None:
        unit = DecisionUnit(
            unit_id="chunk-1:assertion-1",
            text="Cuts are less likely in June.",
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
        )
        questions = build_questions_for_unit(unit)
        ids = [q.question_id for q in questions]
        self.assertEqual(ids, list(expected_question_ids()))
        choice = questions[0]
        self.assertEqual(choice.question_kind, "choice")
        self.assertEqual(choice.options, list(STATEMENT_TYPE_OPTIONS))
        self.assertEqual(choice.question_set_version, QUESTION_SET_VERSION)


class BaselineMappingTest(unittest.TestCase):
    def test_choice_mapping_table(self) -> None:
        self.assertEqual(map_choice_baseline("open_question"), "question")
        self.assertEqual(map_choice_baseline("trade_claim"), "recommendation")
        self.assertEqual(map_choice_baseline("forecast"), "assertion")
        self.assertIsNone(map_choice_baseline("interpretation"))

    def test_subtype_mapping_table(self) -> None:
        self.assertEqual(map_subtype_baseline("causal_claim"), "is_causal")
        self.assertEqual(map_subtype_baseline("risk_condition"), "is_risk_or_scenario")
        self.assertIsNone(map_subtype_baseline("open_question"))


class FakeDecisionModelTest(unittest.TestCase):
    def test_fake_model_preserves_ids_and_distributions(self) -> None:
        model = FakeDecisionModel()
        unit = DecisionUnit(
            unit_id="chunk-1:assertion-1",
            text="We expect two cuts because growth is slowing.",
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
        )
        questions = build_questions_for_unit(unit)
        batch = DecisionBatch(
            batch_id="batch-test",
            shared_context="fixture",
            units=[unit],
            questions=questions,
        )
        result = model.classify_batch(batch)
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.results), len(questions))
        choice = next(r for r in result.results if r.question_id == "statement_type")
        assert choice.distribution is not None
        self.assertEqual(choice.distribution.selected, "assertion")
        self.assertIsNone(choice.distribution.calibrated_probability)
        self.assertAlmostEqual(sum(choice.distribution.probabilities.values()), 1.0, places=6)

    def test_partial_and_failed_coverage(self) -> None:
        model = FakeDecisionModel(
            drop_question_ids={"is_comparative"},
            fail_question_ids={"is_forecast"},
            unknown_question_ids=["ghost_question"],
        )
        unit = DecisionUnit(
            unit_id="chunk-1:assertion-1",
            text="Forecast text",
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
        )
        batch = DecisionBatch(
            batch_id="batch-partial",
            shared_context="",
            units=[unit],
            questions=build_questions_for_unit(unit),
        )
        result = model.classify_batch(batch)
        self.assertEqual(result.status, "partial")
        self.assertTrue(any("is_comparative" in m for m in result.missing_question_ids))
        failed = [r for r in result.results if r.status == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].question_id, "is_forecast")
        self.assertIn("ghost_question", result.unknown_question_ids)

    def test_batch_error_does_not_invent_negatives(self) -> None:
        model = FakeDecisionModel(batch_error="transport down")
        unit = DecisionUnit(
            unit_id="chunk-1:assertion-1",
            text="x",
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
        )
        batch = DecisionBatch(
            batch_id="batch-fail",
            shared_context="",
            units=[unit],
            questions=build_questions_for_unit(unit),
        )
        result = model.classify_batch(batch)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results, [])
        self.assertEqual(result.provider_error, "transport down")


class ShadowClassifierTest(unittest.TestCase):
    def test_stable_ids_and_source_order(self) -> None:
        assertions = [
            _draft(2, 1, "forecast", "Second chunk first assertion"),
            _draft(1, 2, "observation", "First chunk second assertion"),
            _draft(1, 1, "open_question", "First chunk first assertion?"),
        ]
        # Input order should be preserved in the artifact even if chunk/order ids differ.
        classifier = ShadowDecisionClassifier(FakeDecisionModel(), batch_size=2)
        artifact = classifier.classify_assertions(
            assertions,
            document_key="doc-a",
            document_hash="hash-a",
            provenance_by_unit={
                assertion_unit_id(a): {"assertion_key": assertion_unit_id(a)}
                for a in assertions
            },
        )
        self.assertEqual(
            [unit.unit_id for unit in artifact.units],
            [
                "chunk-2:assertion-1",
                "chunk-1:assertion-2",
                "chunk-1:assertion-1",
            ],
        )
        self.assertEqual(artifact.schema_version, ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(len(artifact.batch_results), 2)
        self.assertIsNotNone(artifact.question_set)
        assert artifact.question_set is not None
        self.assertEqual(artifact.question_set.version, QUESTION_SET_VERSION)
        self.assertEqual(
            [q.question_id for q in artifact.question_set.questions],
            list(expected_question_ids()),
        )
        choice = next(
            q for q in artifact.question_set.questions if q.question_id == "statement_type"
        )
        self.assertEqual(choice.question_kind, "choice")
        self.assertTrue(choice.wording)
        self.assertEqual(choice.options, list(STATEMENT_TYPE_OPTIONS))
        evidence = next(
            q
            for q in artifact.question_set.questions
            if q.question_id == "contains_verifiable_evidence"
        )
        self.assertIsNotNone(evidence.noul_criteria)
        for unit in artifact.units:
            self.assertEqual(unit.coverage_status, "full")
            self.assertEqual(unit.provenance.get("assertion_key"), unit.unit_id)
            for result in unit.results:
                assert result.distribution is not None
                self.assertIsNone(result.distribution.calibrated_probability)

    def test_empty_input(self) -> None:
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions([])
        self.assertEqual(artifact.units, [])
        self.assertEqual(artifact.batch_results, [])
        self.assertIsNotNone(artifact.question_set)

    def test_partial_coverage_recorded(self) -> None:
        model = FakeDecisionModel(drop_question_ids={"is_policy_claim"})
        artifact = ShadowDecisionClassifier(model, batch_size=8).classify_assertions(
            [_draft(1, 1, "policy_claim", "Policy may tighten.")]
        )
        self.assertEqual(artifact.incomplete_batch_count, 1)
        self.assertEqual(artifact.units[0].coverage_status, "partial")
        self.assertIn("is_policy_claim", artifact.units[0].missing_question_ids)

    def test_artifact_round_trip(self) -> None:
        classifier = ShadowDecisionClassifier(FakeDecisionModel())
        artifact = classifier.classify_assertions(
            [_draft(1, 1, "forecast", "Cuts later.")],
            document_key="round-trip",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_shadow_artifact(artifact, Path(tmp))
            loaded = load_shadow_artifact(path)
        self.assertEqual(loaded.schema_version, artifact.schema_version)
        self.assertEqual(loaded.units[0].unit_id, "chunk-1:assertion-1")
        self.assertIsNone(
            loaded.units[0].results[0].distribution.calibrated_probability  # type: ignore[union-attr]
        )
        self.assertIsNotNone(loaded.question_set)
        assert loaded.question_set is not None and artifact.question_set is not None
        self.assertEqual(
            loaded.question_set.content_hash, artifact.question_set.content_hash
        )
        self.assertEqual(
            loaded.question_set.questions[0].wording,
            artifact.question_set.questions[0].wording,
        )

    def test_question_set_snapshot_stable_and_standalone(self) -> None:
        first = snapshot_question_set()
        second = snapshot_question_set()
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(len(first.questions), len(expected_question_ids()))
        with tempfile.TemporaryDirectory() as tmp:
            path = write_question_set_snapshot(first, Path(tmp))
            self.assertTrue(path.name.startswith("question_set_"))
            payload = path.read_text(encoding="utf-8")
        self.assertIn("contains_verifiable_evidence", payload)
        self.assertIn(first.content_hash, path.name)

    def test_legacy_artifact_without_question_set_loads(self) -> None:
        classifier = ShadowDecisionClassifier(FakeDecisionModel())
        artifact = classifier.classify_assertions(
            [_draft(1, 1, "forecast", "Cuts later.")],
            document_key="legacy",
        )
        payload = artifact.model_dump(mode="json")
        payload.pop("question_set", None)
        payload["schema_version"] = "decision-shadow-artifact-v1"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(
                __import__("json").dumps(payload),
                encoding="utf-8",
            )
            loaded = load_shadow_artifact(path)
        self.assertIsNone(loaded.question_set)
        self.assertEqual(loaded.units[0].unit_id, "chunk-1:assertion-1")


class FixtureEvalTest(unittest.TestCase):
    def test_fixture_end_to_end_metrics(self) -> None:
        self.assertTrue((fixture_dir() / "units.json").exists())
        assertions = fixture_assertions()
        labels = load_fixture_labels()
        classifier = ShadowDecisionClassifier(FakeDecisionModel(), batch_size=3)
        artifact = classifier.classify_assertions(
            assertions,
            document_key="decision-shadow-fixture-v1",
            document_hash="fixture-sha256-decision-shadow-v1",
            shared_context="fixture",
            provenance_by_unit=fixture_provenance(),
            section_context_by_unit=fixture_section_context(),
        )
        report = evaluate_shadow_artifact(artifact, labels)
        payload = report.as_dict()
        self.assertEqual(report.unit_count, 18)
        self.assertGreater(report.choice_support, 0)
        self.assertIsNotNone(report.choice_macro_f1)
        self.assertIn("is_forecast", report.noul_precision)
        self.assertGreaterEqual(report.coverage_full_rate, 1.0)
        self.assertGreaterEqual(report.provenance_coverage_rate, 1.0)
        self.assertIn("choice_unmapped_labels", report.baseline_limitations)
        self.assertIn(
            "evidence_report",
            report.baseline_limitations["choice_unmapped_labels"],
        )
        # Fake model should agree with mapped Choice baselines when mapped.
        self.assertIsNotNone(report.baseline_choice_agreement)
        self.assertGreater(report.baseline_choice_compared, 0)
        self.assertTrue(payload["notes"][0].startswith("calibrated"))

    def test_overlapping_signals_allowed(self) -> None:
        model = FakeDecisionModel(
            responses={
                ("is_forecast", "chunk-2:assertion-1"): scripted_result(
                    question_id="is_forecast",
                    target_unit_id="chunk-2:assertion-1",
                    status="complete",
                    selected="yes",
                    probabilities={"yes": 0.9, "no": 0.1},
                    raw_probability=0.9,
                ),
                ("is_causal", "chunk-2:assertion-1"): scripted_result(
                    question_id="is_causal",
                    target_unit_id="chunk-2:assertion-1",
                    status="complete",
                    selected="yes",
                    probabilities={"yes": 0.88, "no": 0.12},
                    raw_probability=0.88,
                ),
                ("is_market_impact", "chunk-2:assertion-1"): scripted_result(
                    question_id="is_market_impact",
                    target_unit_id="chunk-2:assertion-1",
                    status="complete",
                    selected="yes",
                    probabilities={"yes": 0.8, "no": 0.2},
                    raw_probability=0.8,
                ),
            }
        )
        artifact = ShadowDecisionClassifier(model).classify_assertions(
            [
                _draft(
                    2,
                    1,
                    "causal_claim",
                    "Sticky inflation will delay cuts and pressure the long end.",
                )
            ]
        )
        unit = artifact.units[0]
        positives = {
            r.question_id
            for r in unit.results
            if r.question_id.startswith("is_")
            and r.distribution
            and r.distribution.selected == "yes"
        }
        self.assertTrue(
            {"is_forecast", "is_causal", "is_market_impact"}.issubset(positives)
        )


class NoCanonicalMutationTest(unittest.TestCase):
    def test_classifier_does_not_import_analyze_document(self) -> None:
        import research_analysis_layer.evals.decision_classifier as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("analyze_document", source)
        self.assertNotIn("from research_analysis_layer.models.agent_outputs", source)
        self.assertNotIn("DocumentAnalysis", source)


if __name__ == "__main__":
    unittest.main()
