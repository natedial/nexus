"""Quarantine-only import of Codex assessments of Jev output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.cli import main as eval_main
from research_analysis_layer.evals.decision_artifacts import write_shadow_artifact
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_codex_assessments import (
    QUARANTINE_FILENAME,
    CodexAssessment,
    CodexImportError,
    export_codex_packets,
    import_codex_assessments,
    load_codex_assessments,
    summarize_codex_assessments,
)
from research_analysis_layer.evals.decision_reviews import sha256_text
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel

TEXT = "Growth will slow next year."


def _artifact():
    return ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
        [
            AssertionDraft(
                chunk_order=1,
                assertion_order=1,
                assertion_type="forecast",
                text=TEXT,
                normalized_text=normalize_text(TEXT),
                summary_text=TEXT,
            )
        ],
        document_key="doc_a",
    )


def _record(artifact, *, assessment_id="a1", pass_id="p1", value=True, **over):
    unit = artifact.units[0]
    record = {
        "assessment_id": assessment_id,
        "pass_id": pass_id,
        "created_at": "2026-10-27T12:00:00Z",
        "document_key": "doc_a",
        "unit_id": unit.unit_id,
        "source_text_sha256": sha256_text(unit.source_text),
        "reported_model": "codex-base",
        "axes": [
            {
                "judgment": {
                    "axis_id": "is_forecast",
                    "state": "labeled",
                    "value": value,
                    "rationale": "States a future outcome.",
                },
                "jev_agreement": "agrees",
            }
        ],
    }
    record.update(over)
    return record


class CodexAssessmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.artifact = _artifact()

    def test_flags_are_fixed_and_cannot_be_promoted(self) -> None:
        base = _record(self.artifact)
        parsed = CodexAssessment.model_validate(base)
        self.assertEqual(parsed.tier, "quarantined")
        self.assertFalse(parsed.independent)
        for field, value in (
            ("tier", "agent_reviewed"),
            ("independent", True),
            ("eligible_for_promotion", True),
            ("provenance_verified", True),
            ("review_state", "agreed"),
            ("correlation_group", "other"),
        ):
            with self.assertRaises(ValueError, msg=field):
                CodexAssessment.model_validate({**base, field: value})

    def test_approval_trace_and_unknown_fields_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CodexAssessment.model_validate(
                _record(self.artifact, approval_trace={"reviewer": "Nate"})
            )

    def test_import_appends_and_rejects_bad_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qdir = Path(tmp) / "quarantine"
            records = [
                _record(self.artifact, assessment_id="ok"),
                _record(self.artifact, assessment_id="ok"),
                _record(self.artifact, assessment_id="badhash", source_text_sha256="0" * 64),
                _record(self.artifact, assessment_id="nounit", unit_id="nope"),
                _record(self.artifact, assessment_id="promo", independent=True),
            ]
            result = import_codex_assessments(
                records, jev_artifacts=[self.artifact], quarantine_dir=qdir
            )
            self.assertEqual(result.accepted, 1)
            reasons = {item["record"]: item["reason"] for item in result.rejected}
            self.assertIn("duplicate", reasons["ok"])
            self.assertIn("hash", reasons["badhash"])
            self.assertIn("not in Jev", reasons["nounit"])
            self.assertIn("schema", reasons["promo"])

            again = import_codex_assessments(
                [_record(self.artifact, assessment_id="ok")],
                jev_artifacts=[self.artifact],
                quarantine_dir=qdir,
            )
            self.assertEqual(again.accepted, 0)
            self.assertEqual(len(load_codex_assessments(qdir / QUARANTINE_FILENAME)), 1)

    def test_refuses_directory_with_human_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "reviews.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(CodexImportError):
                import_codex_assessments(
                    [_record(self.artifact)],
                    jev_artifacts=[self.artifact],
                    quarantine_dir=Path(tmp),
                )
            self.assertFalse((Path(tmp) / QUARANTINE_FILENAME).exists())

    def test_repeated_passes_count_as_one_independent_judgment(self) -> None:
        passes = [
            CodexAssessment.model_validate(
                _record(self.artifact, assessment_id=f"a{i}", pass_id=f"p{i}", value=v)
            )
            for i, v in enumerate((True, True, False))
        ]
        summary = summarize_codex_assessments(passes)
        unit = summary["units"][0]
        self.assertEqual(unit["pass_count"], 3)
        self.assertEqual(unit["independent_judgment_count"], 1)
        self.assertEqual(unit["axes_with_pass_disagreement"], ["is_forecast"])
        self.assertEqual(summary["tier"], "quarantined")

    def test_cli_import_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_path = write_shadow_artifact(self.artifact, tmp_path / "art")
            assessments = tmp_path / "in.jsonl"
            assessments.write_text(
                json.dumps(_record(self.artifact)) + "\n", encoding="utf-8"
            )
            code = eval_main(
                [
                    "decision-codex-import",
                    "--assessments", str(assessments),
                    "--jev-artifact", str(artifact_path),
                    "--quarantine-dir", str(tmp_path / "q"),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((tmp_path / "q" / QUARANTINE_FILENAME).exists())


    def test_span_must_match_source_text(self) -> None:
        bad = _record(self.artifact, assessment_id="span")
        bad["axes"][0]["judgment"]["supporting_spans"] = [
            {"start": 0, "end": 6, "text": "Prices"}
        ]
        good = _record(self.artifact, assessment_id="span_ok")
        good["axes"][0]["judgment"]["supporting_spans"] = [
            {"start": 0, "end": 6, "text": TEXT[:6]}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = import_codex_assessments(
                [bad, good], jev_artifacts=[self.artifact], quarantine_dir=Path(tmp)
            )
        self.assertEqual(result.accepted, 1)
        self.assertIn("span", result.rejected[0]["reason"])


class CodexExportTest(unittest.TestCase):
    def test_export_template_round_trips_through_import(self) -> None:
        artifact = _artifact()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_path = write_shadow_artifact(artifact, tmp_path / "art")
            out = export_codex_packets(
                [artifact_path], output_dir=tmp_path / "pass1", pass_id="pass1"
            )
            for name in ("ASSESSOR.md", "question_set.json", "packets.jsonl", "manifest.json"):
                self.assertTrue((out / name).exists(), name)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["packet_count"], 1)
            self.assertEqual(manifest["tier"], "quarantined")

            packet = json.loads((out / "packets.jsonl").read_text().splitlines()[0])
            self.assertEqual(packet["source_text"], TEXT)
            self.assertIn("is_forecast", packet["jev"]["answers"])

            # Simulate a Codex pass filling the prefilled template.
            record = dict(packet["assessment_template"])
            record["created_at"] = "2026-10-29T12:00:00Z"
            record["reported_model"] = "codex-base"
            record["axes"] = [
                {
                    "judgment": {
                        "axis_id": "is_forecast",
                        "state": "labeled",
                        "value": True,
                        "rationale": "Future outcome.",
                    },
                    "jev_agreement": "unclear",
                }
            ]
            result = import_codex_assessments(
                [record], jev_artifacts=[artifact], quarantine_dir=tmp_path / "q"
            )
            self.assertEqual(result.accepted, 1, result.rejected)
            self.assertEqual(
                load_codex_assessments(tmp_path / "q" / QUARANTINE_FILENAME)[0].assessment_id,
                "pass1:doc_a:" + artifact.units[0].unit_id,
            )

    def test_export_refuses_reused_directory_and_bad_pass_id(self) -> None:
        artifact = _artifact()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_path = write_shadow_artifact(artifact, tmp_path / "art")
            export_codex_packets([artifact_path], output_dir=tmp_path / "p", pass_id="p1")
            with self.assertRaises(ValueError):
                export_codex_packets([artifact_path], output_dir=tmp_path / "p", pass_id="p2")
            with self.assertRaises(ValueError):
                export_codex_packets([artifact_path], output_dir=tmp_path / "x", pass_id="a:b")

    def test_cli_export(self) -> None:
        artifact = _artifact()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifact_path = write_shadow_artifact(artifact, tmp_path / "art")
            code = eval_main(
                [
                    "decision-codex-export",
                    "--jev-artifact", str(artifact_path),
                    "--output", str(tmp_path / "pass"),
                    "--pass-id", "pass1",
                    "--shuffle-seed", "7",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((tmp_path / "pass" / "packets.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
