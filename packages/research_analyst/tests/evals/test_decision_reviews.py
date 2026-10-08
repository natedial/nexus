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
from research_analysis_layer.evals.decision_reviews import (
    ApprovalTrace,
    DecisionReviewRecord,
    ReviewedLabels,
    SourceArtifactReference,
    change_report_markdown,
    coverage_report,
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

    def test_record_requires_all_binary_labels(self) -> None:
        labels = _labels().model_dump(mode="json")
        labels["noul_labels"].pop("is_forecast")
        with self.assertRaisesRegex(ValueError, "missing"):
            ReviewedLabels.model_validate(labels)

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


if __name__ == "__main__":
    unittest.main()
