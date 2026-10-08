"""Tests for structured decision review records and proposed gold releases."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from research_analysis_layer.evals.decision_artifacts import write_shadow_artifact
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_question_set import snapshot_question_set
from research_analysis_layer.evals.decision_metrics import (
    GoldUnitLabel,
    evaluate_shadow_artifact,
)
from research_analysis_layer.evals.decision_reviews import (
    NOUL_QUESTION_IDS,
    ApprovalTrace,
    DecisionReviewRecord,
    ReviewedLabels,
    SourceArtifactReference,
    change_report_markdown,
    coverage_report,
    default_review_dir,
    default_review_records_path,
    gold_labels_from_review_records,
    load_review_records,
    sha256_bytes,
    sha256_text,
    validate_review_records,
    write_release_outputs,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel


def _draft(text: str = "We expect the Fed to cut rates next quarter.") -> AssertionDraft:
    return AssertionDraft(
        chunk_order=1,
        assertion_order=1,
        assertion_type="forecast",
        text=text,
        normalized_text=normalize_text(text),
        summary_text=text,
    )


def _labels() -> ReviewedLabels:
    return ReviewedLabels(
        statement_type="assertion",
        noul_labels={
            "is_observation": False,
            "is_forecast": True,
            "is_causal": False,
            "is_market_impact": False,
            "is_policy_claim": True,
            "is_risk_or_scenario": False,
            "is_comparative": False,
            "is_trade_or_action": False,
            "contains_verifiable_evidence": False,
            "contains_reasoning_bridge": False,
            "is_substantive_author_claim": True,
        },
    )


class ReviewFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.text = "We expect the Fed to cut rates next quarter."
        artifact = ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
            [_draft(self.text)],
            document_key="doc-rates",
            provenance_by_unit={
                "chunk-1:assertion-1": {"assertion_key": "chunk-1:assertion-1"}
            },
        )
        self.artifact = artifact
        self.artifact_path = write_shadow_artifact(artifact, root)
        self.notes_path = root / "REVIEW_NOTES.md"
        self.note_reference = "Agreed by Nate: clear forecast with a policy signal."
        self.notes_path.write_text(self.note_reference + "\n", encoding="utf-8")

    def record(
        self,
        *,
        review_id: str = "review-rates-001",
        status: str = "agreed",
        **updates: object,
    ) -> DecisionReviewRecord:
        question_set = snapshot_question_set()
        payload: dict[str, object] = {
            "review_id": review_id,
            "document_id": "doc-rates",
            "document_type": "rates",
            "unit_id": "chunk-1:assertion-1",
            "reviewed_text": self.text,
            "reviewed_text_sha256": sha256_text(self.text),
            "stored_model_input_sha256": sha256_text(self.text),
            "question_set_version": question_set.version,
            "question_set_content_hash": question_set.content_hash,
            "provider": self.artifact.provider,
            "model_version": self.artifact.model_version,
            "adapter_version": self.artifact.adapter_version,
            "labels": _labels().model_dump(mode="json"),
            "dominant_signals": ["is_forecast"],
            "secondary_signals": ["is_policy_claim"],
            "reviewer": "Nate",
            "review_date": date(2026, 10, 7),
            "status": status,
            "rationale": "The sentence is primarily a forecast.",
            "issue_tags": ["clear-forecast"],
            "source_artifact": SourceArtifactReference(
                path=self.artifact_path.name,
                sha256=sha256_bytes(self.artifact_path.read_bytes()),
            ).model_dump(mode="json"),
        }
        if status == "agreed":
            payload["approval_trace"] = ApprovalTrace(
                source_path=self.notes_path.name,
                source_sha256=sha256_bytes(self.notes_path.read_bytes()),
                note_reference=self.note_reference,
            ).model_dump(mode="json")
        payload.update(updates)
        return DecisionReviewRecord.model_validate(payload)


class DecisionReviewRecordTest(unittest.TestCase):
    def test_agreed_record_requires_approval_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "approval_trace"):
                fixture.record(approval_trace=None)

    def test_sparse_noul_labels_are_unreviewed_not_false(self) -> None:
        labels = ReviewedLabels(
            statement_type="assertion",
            noul_labels={"is_forecast": True, "is_trade_or_action": False},
        )
        self.assertEqual(labels.noul_labels.get("is_forecast"), True)
        self.assertEqual(labels.noul_labels.get("is_trade_or_action"), False)
        self.assertNotIn("is_observation", labels.noul_labels)
        self.assertEqual(labels.label_completeness, "partial")
        self.assertIn("is_observation", labels.unreviewed_noul_ids)

    def test_null_noul_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absent, not null"):
            ReviewedLabels.model_validate(
                {
                    "statement_type": "assertion",
                    "noul_labels": {"is_forecast": None},
                }
            )

    def test_unknown_noul_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown question ids"):
            ReviewedLabels(
                statement_type="assertion",
                noul_labels={"not_a_noul": True},
            )

    def test_empty_noul_labels_are_partial_unreviewed(self) -> None:
        labels = ReviewedLabels(statement_type="assertion")
        self.assertEqual(labels.noul_labels, {})
        self.assertEqual(labels.label_completeness, "partial")
        self.assertEqual(labels.unreviewed_noul_ids, list(NOUL_QUESTION_IDS))

    def test_completeness_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "label_completeness"):
                fixture.record(label_completeness="partial")
            with self.assertRaisesRegex(ValueError, "unreviewed_noul_ids"):
                fixture.record(unreviewed_noul_ids=["is_forecast"])

    def test_binary_labels_do_not_coerce_strings(self) -> None:
        labels = _labels().model_dump(mode="json")
        labels["noul_labels"]["is_forecast"] = "false"
        with self.assertRaisesRegex(ValueError, "JSON booleans"):
            ReviewedLabels.model_validate(labels)

    def test_record_rejects_text_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "reviewed_text_sha256"):
                fixture.record(reviewed_text_sha256="0" * 64)

    def test_candidate_cannot_carry_approval_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            approval = ApprovalTrace(
                source_path=fixture.notes_path.name,
                source_sha256=sha256_bytes(fixture.notes_path.read_bytes()),
                note_reference=fixture.note_reference,
            ).model_dump(mode="json")
            with self.assertRaisesRegex(ValueError, "candidate records"):
                fixture.record(status="candidate", approval_trace=approval)


class DecisionReviewValidationTest(unittest.TestCase):
    def test_exact_artifact_and_approval_sources_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            report = validate_review_records(
                [fixture.record()], artifact_root=fixture.root
            )
            self.assertTrue(report.valid, report.model_dump(mode="json"))
            self.assertEqual(report.agreed_count, 1)

    def test_source_text_drift_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            model_input = fixture.text + " Unreviewed suffix."
            record = fixture.record(
                stored_model_input=model_input,
                stored_model_input_sha256=sha256_text(model_input),
            )
            report = validate_review_records([record], artifact_root=fixture.root)
            self.assertFalse(report.valid)
            self.assertIn("source_text_drift", {issue.code for issue in report.issues})

    def test_duplicate_active_unit_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            first = fixture.record()
            second = fixture.record(review_id="review-rates-002")
            report = validate_review_records([first, second])
            self.assertFalse(report.valid)
            self.assertIn(
                "duplicate_active_unit_version", {issue.code for issue in report.issues}
            )

    def test_superseded_history_can_be_retained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            prior_payload = fixture.record().model_dump(mode="json")
            prior_payload.update({"status": "superseded"})
            prior = DecisionReviewRecord.model_validate(prior_payload)
            current = fixture.record(
                review_id="review-rates-002",
                supersedes_review_id=prior.review_id,
            )
            report = validate_review_records([prior, current], artifact_root=fixture.root)
            self.assertTrue(report.valid, report.model_dump(mode="json"))
            self.assertEqual(report.history_count, 1)

    def test_artifact_hash_drift_stops_deeper_source_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            record = fixture.record()
            fixture.artifact_path.write_text("{}\n", encoding="utf-8")
            report = validate_review_records([record], artifact_root=fixture.root)
            self.assertFalse(report.valid)
            self.assertIn("artifact_hash_drift", {issue.code for issue in report.issues})


class DecisionReviewReportingTest(unittest.TestCase):
    def test_coverage_never_mixes_candidates_into_gold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            agreed = fixture.record()
            candidate_payload = agreed.model_dump(mode="json")
            candidate_payload.update(
                {
                    "review_id": "review-rates-candidate",
                    "document_id": "doc-rates-2",
                    "unit_id": "chunk-2:assertion-1",
                    "status": "candidate",
                    "approval_trace": None,
                }
            )
            candidate = DecisionReviewRecord.model_validate(candidate_payload)
            report = coverage_report([agreed, candidate])
            self.assertEqual(report["agreed_gold"]["record_count"], 1)
            self.assertEqual(report["candidates"]["record_count"], 1)

    def test_change_report_names_additions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            report = change_report_markdown([fixture.record()])
            self.assertIn("Active additions: 1", report)
            self.assertIn("`doc-rates` / `chunk-1:assertion-1`", report)

    def test_release_outputs_include_only_agreed_as_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = ReviewFixture(root)
            agreed = fixture.record()
            candidate_artifact = ShadowDecisionClassifier(
                FakeDecisionModel()
            ).classify_assertions(
                [_draft(fixture.text)],
                document_key="doc-rates-2",
                provenance_by_unit={
                    "chunk-1:assertion-1": {
                        "assertion_key": "chunk-1:assertion-1"
                    }
                },
            )
            candidate_artifact_path = write_shadow_artifact(
                candidate_artifact, root, prefix="candidate"
            )
            candidate_payload = agreed.model_dump(mode="json")
            candidate_payload.update(
                {
                    "review_id": "review-rates-candidate",
                    "document_id": "doc-rates-2",
                    "status": "candidate",
                    "approval_trace": None,
                    "source_artifact": {
                        "path": candidate_artifact_path.name,
                        "sha256": sha256_bytes(candidate_artifact_path.read_bytes()),
                    },
                }
            )
            candidate = DecisionReviewRecord.model_validate(candidate_payload)
            records_path = root / "records.jsonl"
            records_path.write_text(
                "\n".join(
                    json.dumps(record.model_dump(mode="json"))
                    for record in (agreed, candidate)
                )
                + "\n",
                encoding="utf-8",
            )
            loaded = load_review_records(records_path)
            validation = validate_review_records(loaded, artifact_root=root)
            output_dir = root / "release"
            write_release_outputs(
                records=loaded,
                records_path=records_path,
                output_dir=output_dir,
                validation=validation,
                release_version="decision-gold-test",
            )
            manifest = json.loads(
                (output_dir / "release_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["eligible_review_ids"], [agreed.review_id])
            self.assertTrue(manifest["safety"]["candidates_excluded"])
            self.assertTrue((output_dir / "CHANGE_REPORT.md").is_file())
            self.assertTrue((output_dir / "coverage.json").is_file())
            schema = json.loads(
                (output_dir / "review_record.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("review_id", schema["properties"])

    def test_unverified_records_are_not_release_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = ReviewFixture(root)
            agreed = fixture.record()
            records_path = root / "records.jsonl"
            records_path.write_text(
                json.dumps(agreed.model_dump(mode="json")) + "\n",
                encoding="utf-8",
            )
            validation = validate_review_records([agreed])
            output_dir = root / "release"
            write_release_outputs(
                records=[agreed],
                records_path=records_path,
                output_dir=output_dir,
                validation=validation,
                release_version="decision-gold-test",
            )
            manifest = json.loads(
                (output_dir / "release_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["release_status"], "proposed_unverified")
            self.assertEqual(manifest["eligible_review_ids"], [])

    def test_partial_agreed_records_are_split_from_full_vector_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = ReviewFixture(root)
            agreed = fixture.record(
                labels={
                    "statement_type": "assertion",
                    "noul_labels": {
                        "is_forecast": True,
                        "is_trade_or_action": False,
                    },
                }
            )
            self.assertEqual(agreed.label_completeness, "partial")
            records_path = root / "records.jsonl"
            records_path.write_text(
                json.dumps(agreed.model_dump(mode="json")) + "\n",
                encoding="utf-8",
            )
            validation = validate_review_records([agreed], artifact_root=root)
            output_dir = root / "release"
            write_release_outputs(
                records=[agreed],
                records_path=records_path,
                output_dir=output_dir,
                validation=validation,
                release_version="decision-gold-test",
            )
            manifest = json.loads(
                (output_dir / "release_manifest.json").read_text(encoding="utf-8")
            )
            coverage = json.loads(
                (output_dir / "coverage.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["eligible_review_ids"], [agreed.review_id])
            self.assertEqual(manifest["eligible_complete_review_ids"], [])
            self.assertEqual(
                manifest["eligible_partial_review_ids"], [agreed.review_id]
            )
            self.assertTrue(
                manifest["safety"]["partial_records_excluded_from_full_vector_metrics"]
            )
            self.assertTrue(manifest["safety"]["unreviewed_noul_labels_not_inferred"])
            gold = coverage["agreed_gold"]
            self.assertEqual(gold["partial_record_count"], 1)
            self.assertEqual(gold["complete_record_count"], 0)
            self.assertEqual(gold["noul_labels"]["is_forecast"]["reviewed"], 1)
            self.assertEqual(gold["noul_labels"]["is_forecast"]["yes"], 1)
            self.assertEqual(gold["noul_labels"]["is_observation"]["reviewed"], 0)
            self.assertEqual(gold["noul_labels"]["is_observation"]["unreviewed"], 1)
            self.assertEqual(gold["noul_labels"]["is_observation"]["no"], 0)


class ImportedDecisionReviewTest(unittest.TestCase):
    def test_checked_in_agreed_notes_validate_as_partial_gold(self) -> None:
        records_path = default_review_records_path()
        self.assertTrue(records_path.is_file(), records_path)
        records = load_review_records(records_path)
        report = validate_review_records(
            records, artifact_root=default_review_dir() / "sources"
        )
        self.assertTrue(report.valid, report.model_dump(mode="json"))
        self.assertEqual(report.agreed_count, 2)
        self.assertEqual(report.candidate_count, 0)
        self.assertTrue(all(record.status == "agreed" for record in records))
        self.assertTrue(
            all(record.label_completeness == "partial" for record in records)
        )
        by_id = {record.review_id: record for record in records}
        first = by_id["review-doc002-chunk6-assertion2-20260930"]
        second = by_id["review-doc003-chunk7-assertion1-20261002"]
        self.assertEqual(
            first.labels.noul_labels,
            {
                "is_forecast": True,
                "is_causal": True,
                "is_trade_or_action": False,
                "contains_reasoning_bridge": True,
            },
        )
        self.assertEqual(
            second.labels.noul_labels,
            {
                "is_forecast": False,
                "is_causal": False,
                "is_trade_or_action": True,
                "contains_reasoning_bridge": False,
            },
        )
        self.assertNotIn("is_observation", first.labels.noul_labels)
        self.assertNotIn("is_observation", second.labels.noul_labels)

    def test_require_complete_excludes_partial_agreed_records(self) -> None:
        records = load_review_records(default_review_records_path())
        self.assertEqual(
            gold_labels_from_review_records(records, require_complete=True),
            [],
        )
        gold = gold_labels_from_review_records(records)
        self.assertEqual(len(gold), 2)
        self.assertTrue(all(label.document_id for label in gold))
        self.assertTrue(all(label.label_completeness == "partial" for label in gold))
        self.assertTrue(
            all("is_observation" not in label.noul_labels for label in gold)
        )
        by_doc = {label.document_id: label for label in gold}
        self.assertIn(
            by_doc["doc_002"].reviewed_text or "",
            by_doc["doc_002"].stored_model_input or "",
        )
        self.assertNotEqual(
            by_doc["doc_002"].reviewed_text,
            by_doc["doc_002"].stored_model_input,
        )

    def test_evaluation_scores_only_supplied_noul_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ReviewFixture(Path(tmp))
            gold = [
                GoldUnitLabel(
                    unit_id="chunk-1:assertion-1",
                    document_id="doc-rates",
                    statement_type="assertion",
                    noul_labels={
                        "is_forecast": True,
                        "is_trade_or_action": False,
                    },
                )
            ]
            report = evaluate_shadow_artifact(fixture.artifact, gold)
            self.assertEqual(report.unit_count, 1)
            self.assertEqual(report.partial_label_unit_count, 1)
            self.assertEqual(report.complete_label_unit_count, 0)
            self.assertEqual(report.noul_reviewed["is_forecast"], 1)
            self.assertEqual(report.noul_reviewed["is_trade_or_action"], 1)
            self.assertEqual(report.noul_reviewed["is_observation"], 0)
            self.assertNotIn("is_observation", report.noul_support)
            self.assertIn("partial-label units excluded", " ".join(report.notes))


if __name__ == "__main__":
    unittest.main()
