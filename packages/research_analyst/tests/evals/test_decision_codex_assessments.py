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
    compare_codex_to_jev,
    export_codex_packets,
    import_codex_assessments,
    load_codex_assessments,
    summarize_codex_assessments,
)
from research_analysis_layer.evals.decision_reviews import sha256_text
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel

TEXT = "Growth will slow next year."
OTHER_TEXTS = ("Rates will stay on hold.", "Spreads should widen into year end.")


def _artifact(texts=(TEXT,)):
    return ShadowDecisionClassifier(FakeDecisionModel()).classify_assertions(
        [
            AssertionDraft(
                chunk_order=1,
                assertion_order=order,
                assertion_type="forecast",
                text=text,
                normalized_text=normalize_text(text),
                summary_text=text,
            )
            for order, text in enumerate(texts, start=1)
        ],
        document_key="doc_a",
    )


def _record(
    artifact, *, assessment_id="a1", pass_id="p1", value=True, unit_index=0, **over
):
    unit = artifact.units[unit_index]
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
                    "--expected-model", "codex-base",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((tmp_path / "q" / QUARANTINE_FILENAME).exists())

            report_path = tmp_path / "compare.json"
            code = eval_main(
                [
                    "decision-codex-compare",
                    "--quarantine-dir", str(tmp_path / "q"),
                    "--jev-artifact", str(artifact_path),
                    "--output", str(report_path),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("p1", json.loads(report_path.read_text())["passes"])


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

    def test_blind_records_cannot_carry_jev_agreement(self) -> None:
        record = _record(self.artifact)
        record["axes"][0]["jev_agreement"] = "agrees"
        with self.assertRaises(ValueError):
            CodexAssessment.model_validate(record)
        with self.assertRaises(ValueError):
            CodexAssessment.model_validate({**_record(self.artifact), "saw_jev_output": True})

    def test_legacy_v1_records_load_but_are_not_imported(self) -> None:
        legacy = _record(
            self.artifact,
            schema_version="decision-codex-assessment-v1",
            saw_jev_output=True,
        )
        legacy["axes"][0]["jev_agreement"] = "agrees"
        self.assertTrue(CodexAssessment.model_validate(legacy).saw_jev_output)
        with self.assertRaises(ValueError):
            CodexAssessment.model_validate({**legacy, "saw_jev_output": False})
        with tempfile.TemporaryDirectory() as tmp:
            result = import_codex_assessments(
                [legacy], jev_artifacts=[self.artifact], quarantine_dir=Path(tmp)
            )
        self.assertEqual(result.accepted, 0)
        self.assertIn("blind packet", result.rejected[0]["reason"])

    def test_expected_model_mismatch_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = import_codex_assessments(
                [
                    _record(self.artifact, assessment_id="right", reported_model=" Codex-Base "),
                    _record(self.artifact, assessment_id="wrong", reported_model="gpt-other"),
                ],
                jev_artifacts=[self.artifact],
                quarantine_dir=Path(tmp),
                expected_model="codex-base",
            )
        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.rejected[0]["record"], "wrong")
        self.assertIn("expected", result.rejected[0]["reason"])

    def test_import_flags_cannot_be_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = import_codex_assessments(
                [_record(self.artifact, import_flags=[])],
                jev_artifacts=[self.artifact],
                quarantine_dir=Path(tmp),
            )
        self.assertEqual(result.accepted, 0)
        self.assertIn("importer", result.rejected[0]["reason"])

    def test_whole_text_spans_on_several_axes_are_flagged(self) -> None:
        whole = {"start": 0, "end": len(TEXT), "text": TEXT}
        record = _record(self.artifact, assessment_id="whole")
        record["axes"] = [
            {
                "judgment": {
                    "axis_id": axis_id,
                    "state": "labeled",
                    "value": value,
                    "rationale": f"{axis_id} rationale.",
                    "supporting_spans": [whole],
                }
            }
            for axis_id, value in (("is_forecast", True), ("is_causal", False))
        ]
        single = _record(self.artifact, assessment_id="single")
        single["axes"][0]["judgment"]["supporting_spans"] = [whole]
        with tempfile.TemporaryDirectory() as tmp:
            result = import_codex_assessments(
                [record, single], jev_artifacts=[self.artifact], quarantine_dir=Path(tmp)
            )
            stored = {
                r.assessment_id: r.import_flags
                for r in load_codex_assessments(Path(tmp) / QUARANTINE_FILENAME)
            }
        self.assertEqual(result.accepted, 2)
        self.assertEqual(stored, {"whole": ["whole_text_span"], "single": []})
        self.assertEqual(result.flagged, [{"record": "whole", "flags": ["whole_text_span"]}])

    def test_same_rationale_across_units_is_flagged(self) -> None:
        artifact = _artifact((TEXT, *OTHER_TEXTS))
        records = [
            _record(artifact, assessment_id=f"u{i}", unit_index=i) for i in range(3)
        ]
        records[2]["axes"][0]["judgment"]["rationale"] = "  states A future   OUTCOME. "
        two_units = [
            _record(artifact, assessment_id=f"v{i}", pass_id="p2", unit_index=i)
            for i in range(2)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            flagged = import_codex_assessments(
                records, jev_artifacts=[artifact], quarantine_dir=Path(tmp) / "a"
            ).flagged
            unflagged = import_codex_assessments(
                two_units, jev_artifacts=[artifact], quarantine_dir=Path(tmp) / "b"
            ).flagged
        self.assertEqual(
            [item["flags"] for item in flagged], [["templated_rationale:is_forecast"]] * 3
        )
        self.assertEqual(unflagged, [])

    def test_compare_counts_per_pass_and_lists_disagreements(self) -> None:
        unit = self.artifact.units[0]
        jev_forecast = next(r for r in unit.results if r.question_id == "is_forecast")
        jev_value = jev_forecast.distribution.selected == "yes"
        passes = [
            CodexAssessment.model_validate(
                _record(self.artifact, assessment_id=f"a{i}", pass_id=f"p{i}", value=value)
            )
            for i, value in enumerate((jev_value, not jev_value))
        ]
        legacy = CodexAssessment.model_validate(
            _record(
                self.artifact,
                assessment_id="old",
                schema_version="decision-codex-assessment-v1",
                saw_jev_output=True,
            )
        )
        report = compare_codex_to_jev([*passes, legacy], jev_artifacts=[self.artifact])
        self.assertEqual(report["passes"]["p0"]["is_forecast"]["agrees"], 1)
        self.assertEqual(report["passes"]["p1"]["is_forecast"]["disagrees"], 1)
        self.assertEqual(report["skipped_legacy_v1"], 1)
        self.assertEqual(len(report["disagreements"]), 1)
        self.assertEqual(report["disagreements"][0]["jev_value"], jev_value)
        self.assertEqual(report["tier"], "quarantined")


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
            self.assertNotIn("jev", packet)
            self.assertNotIn("assertion_type", packet)
            self.assertNotIn("answers", json.dumps(packet))
            self.assertEqual(manifest["stage"], "blind")

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
