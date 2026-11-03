"""Quarantine-only import of Codex assessments of Jev decision outputs.

Assessments produced by an interactive Codex session outside the API-routed
harness carry no verified call provenance and share one model family across
passes. They therefore get their own record type: it cannot be read as an
``AgentReference`` or ``AgentJudgment``, carries no approval trace, and its
tier, independence, and promotion flags are fixed literals that validation
refuses to change. Repeated passes are correlated evidence and are summarized
as a single independent judgment per unit.

The workflow has two stages. Stage 1 exports blind packets (no Jev output) and
Codex labels each unit from the text alone. Stage 2 compares those labels with
Jev's answers deterministically, so Codex never anchors on Jev. v1 records,
which saw Jev output, still load but are no longer imported.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AxisJudgment,
)
from research_analysis_layer.evals.decision_question_set import snapshot_question_set
from research_analysis_layer.evals.decision_reviews import sha256_bytes, sha256_text
from research_analysis_layer.models.decision_models import (
    ShadowClassificationArtifact,
    UnitClassificationRecord,
)

CODEX_ASSESSMENT_SCHEMA_VERSION = "decision-codex-assessment-v2"
LEGACY_ASSESSMENT_SCHEMA_VERSION = "decision-codex-assessment-v1"
CODEX_PACKET_SCHEMA_VERSION = "decision-codex-packet-v2"
CODEX_EXPORT_MANIFEST_SCHEMA_VERSION = "decision-codex-export-v2"
CODEX_COMPARISON_SCHEMA_VERSION = "decision-codex-comparison-v1"
QUARANTINE_FILENAME = "codex_assessments.jsonl"
CORRELATION_GROUP = "codex"
# Directories holding human-reviewed records; quarantine output never goes there.
_PROTECTED_MARKERS = ("reviews.jsonl",)
# Review flags (never rejections). A span covering this share of the source on
# two or more axes grounds nothing axis-specific; the same rationale on this
# many units in one import reads as a template rather than a judgment.
_WHOLE_TEXT_SPAN_SHARE = 0.9
_WHOLE_TEXT_SPAN_MIN_AXES = 2
_TEMPLATED_RATIONALE_MIN_UNITS = 3


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodexAxisAssessment(StrictModel):
    """Codex's sparse label for one axis.

    ``jev_agreement`` exists only on v1 records, which saw Jev output; blind v2
    records leave it unset and agreement is computed in stage 2.
    """

    judgment: AxisJudgment
    jev_agreement: Literal["agrees", "disagrees", "unclear"] | None = None


class PolicyQuestion(StrictModel):
    """Compact taxonomy/policy escalation, grouped by root question."""

    question: str = Field(min_length=1, max_length=400)
    axis_ids: list[str] = Field(min_length=1)

    @field_validator("axis_ids")
    @classmethod
    def _known_axes(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(AXIS_IDS))
        if unknown:
            raise ValueError(f"unknown axis ids: {unknown}")
        return sorted(set(value))


class CodexAssessment(StrictModel):
    """One Codex pass over one Jev-classified unit. Always quarantined."""

    schema_version: Literal[
        "decision-codex-assessment-v1", "decision-codex-assessment-v2"
    ] = CODEX_ASSESSMENT_SCHEMA_VERSION
    assessment_id: str = Field(min_length=1)
    pass_id: str = Field(min_length=1)
    created_at: datetime
    # Source identity, verified against the Jev artifact at import.
    document_key: str = Field(min_length=1)
    unit_id: str = Field(min_length=1)
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Self-reported and unverifiable; recorded for audit, never trusted.
    reported_model: str = Field(min_length=1)
    reported_session: str | None = None
    axes: list[CodexAxisAssessment] = Field(min_length=1)
    policy_questions: list[PolicyQuestion] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=2000)
    # Set only by the importer; review prompts, never grounds for rejection.
    import_flags: list[str] = Field(default_factory=list)

    # Fixed by construction; any other value fails validation.
    tier: Literal["quarantined"] = "quarantined"
    review_state: Literal["provisional"] = "provisional"
    correlation_group: Literal["codex"] = CORRELATION_GROUP
    # True only on legacy v1 records; blind v2 records must leave it False.
    saw_jev_output: bool = False
    provenance_verified: Literal[False] = False
    independent: Literal[False] = False
    eligible_for_promotion: Literal[False] = False

    @model_validator(mode="after")
    def _stage_consistent(self) -> CodexAssessment:
        if self.schema_version == LEGACY_ASSESSMENT_SCHEMA_VERSION:
            if not self.saw_jev_output:
                raise ValueError("v1 assessments saw Jev output")
        else:
            if self.saw_jev_output:
                raise ValueError("blind v2 assessments cannot have seen Jev output")
            if any(axis.jev_agreement is not None for axis in self.axes):
                raise ValueError("blind v2 assessments cannot set jev_agreement")
        return self

    @field_validator("axes")
    @classmethod
    def _unique_axes(
        cls, value: list[CodexAxisAssessment]
    ) -> list[CodexAxisAssessment]:
        ids = [item.judgment.axis_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("an assessment cannot repeat an axis")
        return value


class CodexImportError(ValueError):
    """Raised when an import must be refused as a whole."""


class CodexImportResult(StrictModel):
    accepted: int
    rejected: list[dict[str, Any]]
    flagged: list[dict[str, Any]] = Field(default_factory=list)
    output_path: str


def _units_by_identity(
    artifacts: Iterable[ShadowClassificationArtifact],
) -> dict[tuple[str, str], UnitClassificationRecord]:
    units: dict[tuple[str, str], UnitClassificationRecord] = {}
    for artifact in artifacts:
        for unit in artifact.units:
            document = unit.document_key or artifact.document_key
            if not document:
                continue
            units[(document, unit.unit_id)] = unit
    return units


def _span_error(record: CodexAssessment, source_text: str) -> str | None:
    for axis in record.axes:
        for span in axis.judgment.supporting_spans:
            if source_text[span.start : span.end] != span.text:
                return (
                    f"supporting span {span.start}:{span.end} on "
                    f"{axis.judgment.axis_id} does not match source text"
                )
    return None


def _whole_text_span_axes(record: CodexAssessment, source_text: str) -> list[str]:
    if not source_text:
        return []
    threshold = _WHOLE_TEXT_SPAN_SHARE * len(source_text)
    return sorted(
        axis.judgment.axis_id
        for axis in record.axes
        if any(span.end - span.start >= threshold for span in axis.judgment.supporting_spans)
    )


def _normalized_rationale(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _review_flags(
    accepted: Sequence[tuple[CodexAssessment, str]],
) -> dict[str, list[str]]:
    """Flags per assessment_id for whole-text spans and templated rationales."""
    flags: dict[str, list[str]] = defaultdict(list)
    for record, source_text in accepted:
        if len(_whole_text_span_axes(record, source_text)) >= _WHOLE_TEXT_SPAN_MIN_AXES:
            flags[record.assessment_id].append("whole_text_span")

    units_by_rationale: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for record, _ in accepted:
        for axis in record.axes:
            key = (axis.judgment.axis_id, _normalized_rationale(axis.judgment.rationale))
            units_by_rationale[key].add((record.document_key, record.unit_id))
    templated = {
        key for key, units in units_by_rationale.items()
        if len(units) >= _TEMPLATED_RATIONALE_MIN_UNITS
    }
    for record, _ in accepted:
        for axis_id in sorted(
            {
                axis.judgment.axis_id
                for axis in record.axes
                if (axis.judgment.axis_id, _normalized_rationale(axis.judgment.rationale))
                in templated
            }
        ):
            flags[record.assessment_id].append(f"templated_rationale:{axis_id}")
    return dict(flags)


def _normalized_model(name: str) -> str:
    return name.strip().lower()


def _check_quarantine_dir(quarantine_dir: Path) -> None:
    for marker in _PROTECTED_MARKERS:
        if (quarantine_dir / marker).exists():
            raise CodexImportError(
                f"{quarantine_dir} holds {marker}; refusing to write quarantined "
                "assessments beside human-reviewed records"
            )


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["assessment_id"])
    return ids


def import_codex_assessments(
    records: Sequence[Mapping[str, Any]],
    *,
    jev_artifacts: Iterable[ShadowClassificationArtifact],
    quarantine_dir: Path,
    expected_model: str | None = None,
) -> CodexImportResult:
    """Validate and append blind assessments to the quarantine file.

    Per-record problems are reported in ``rejected`` and do not stop valid
    records. ``expected_model`` rejects records whose self-reported model is
    not the one the pass was meant to run as. Accepted records may carry
    ``import_flags`` for review. Existing lines are never rewritten.
    """
    _check_quarantine_dir(quarantine_dir)
    units = _units_by_identity(jev_artifacts)
    output_path = quarantine_dir / QUARANTINE_FILENAME
    seen = _existing_ids(output_path)

    accepted: list[tuple[CodexAssessment, str]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        label = str(raw.get("assessment_id", f"record[{index}]"))
        if "import_flags" in raw:
            rejected.append({"record": label, "reason": "import_flags are set by the importer"})
            continue
        try:
            record = CodexAssessment.model_validate(raw)
        except ValueError as exc:
            rejected.append({"record": label, "reason": f"schema: {exc}"})
            continue
        unit = units.get((record.document_key, record.unit_id))
        span_error = _span_error(record, unit.source_text) if unit else None
        if record.schema_version == LEGACY_ASSESSMENT_SCHEMA_VERSION:
            rejected.append(
                {
                    "record": label,
                    "reason": "v1 assessments saw Jev output; export a blind packet",
                }
            )
        elif expected_model is not None and _normalized_model(
            record.reported_model
        ) != _normalized_model(expected_model):
            rejected.append(
                {
                    "record": label,
                    "reason": (
                        f"reported_model {record.reported_model!r} is not the "
                        f"expected {expected_model!r}"
                    ),
                }
            )
        elif unit is None:
            rejected.append({"record": label, "reason": "unit not in Jev artifacts"})
        elif sha256_text(unit.source_text) != record.source_text_sha256:
            rejected.append({"record": label, "reason": "source text hash mismatch"})
        elif span_error is not None:
            rejected.append({"record": label, "reason": span_error})
        elif record.assessment_id in seen:
            rejected.append({"record": label, "reason": "duplicate assessment_id"})
        else:
            seen.add(record.assessment_id)
            accepted.append((record, unit.source_text))

    flags = _review_flags(accepted)
    flagged_records = [
        record.model_copy(update={"import_flags": flags.get(record.assessment_id, [])})
        for record, _ in accepted
    ]
    if flagged_records:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            for record in flagged_records:
                handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
                handle.write("\n")
    return CodexImportResult(
        accepted=len(flagged_records),
        rejected=rejected,
        flagged=[
            {"record": record.assessment_id, "flags": record.import_flags}
            for record in flagged_records
            if record.import_flags
        ],
        output_path=str(output_path),
    )


def assessor_prompt_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "prompts"
        / "evals"
        / "decision_codex"
        / "assessor.md"
    )


def _jev_answers(unit: UnitClassificationRecord) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for result in unit.results:
        distribution = result.distribution
        answers[result.question_id] = {
            "status": result.status,
            "selected": distribution.selected if distribution else None,
            "raw_probability": distribution.raw_probability if distribution else None,
            "error": result.error,
        }
    return answers


def export_codex_packets(
    artifact_paths: Sequence[Path],
    *,
    output_dir: Path,
    pass_id: str,
    shuffle_seed: int | None = None,
) -> Path:
    """Write a blind stage-1 work packet for one Codex pass.

    Packets carry the source text and the frozen questions, with identity
    fields prefilled so source hashes are never hand-typed. They omit Jev
    output and the extractor's heuristic ``assertion_type``, either of which
    would anchor the labels. A distinct ``pass_id`` and ``shuffle_seed`` per
    pass varies order, but passes remain correlated.
    """
    if not pass_id.strip() or any(ch in pass_id for ch in ":/\\"):
        raise ValueError("pass_id must be non-empty and contain no ':' or slashes")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"{output_dir} is not empty; use a fresh directory per pass")

    loaded: list[tuple[Path, ShadowClassificationArtifact]] = []
    for path in artifact_paths:
        loaded.append(
            (path, ShadowClassificationArtifact.model_validate_json(path.read_text("utf-8")))
        )
    snapshots = {
        artifact.question_set.content_hash: artifact.question_set
        for _, artifact in loaded
        if artifact.question_set is not None
    }
    if len(snapshots) > 1:
        raise ValueError("artifacts use different question sets; export them separately")
    question_set = (
        next(iter(snapshots.values())) if snapshots else snapshot_question_set()
    )

    packets: list[dict[str, Any]] = []
    for _, artifact in loaded:
        for unit in artifact.units:
            document = unit.document_key or artifact.document_key
            if not document:
                continue
            source_hash = sha256_text(unit.source_text)
            packets.append(
                {
                    "packet_schema": CODEX_PACKET_SCHEMA_VERSION,
                    "pass_id": pass_id,
                    "document_key": document,
                    "unit_id": unit.unit_id,
                    "source_text": unit.source_text,
                    "source_text_sha256": source_hash,
                    "assessment_template": {
                        "schema_version": CODEX_ASSESSMENT_SCHEMA_VERSION,
                        "assessment_id": f"{pass_id}:{document}:{unit.unit_id}",
                        "pass_id": pass_id,
                        "created_at": None,
                        "document_key": document,
                        "unit_id": unit.unit_id,
                        "source_text_sha256": source_hash,
                        "reported_model": None,
                        "axes": [],
                        "policy_questions": [],
                    },
                }
            )
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(packets)

    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_bytes = assessor_prompt_path().read_bytes()
    (output_dir / "ASSESSOR.md").write_bytes(prompt_bytes)
    (output_dir / "question_set.json").write_text(
        json.dumps(question_set.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with (output_dir / "packets.jsonl").open("w", encoding="utf-8") as handle:
        for packet in packets:
            handle.write(json.dumps(packet, sort_keys=True))
            handle.write("\n")
    manifest = {
        "schema_version": CODEX_EXPORT_MANIFEST_SCHEMA_VERSION,
        "stage": "blind",
        "pass_id": pass_id,
        "shuffle_seed": shuffle_seed,
        "packet_count": len(packets),
        "assessor_prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "question_set_version": question_set.version,
        "question_set_hash": question_set.content_hash,
        "jev_artifacts": [
            {"path": str(path), "sha256": sha256_bytes(path.read_bytes())}
            for path, _ in loaded
        ],
        "tier": "quarantined",
        "note": (
            "Blind packet: no Jev output. Assessments import only as quarantined, "
            "correlated evidence; compare with Jev afterwards via decision-codex-compare."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return output_dir


def load_codex_assessments(path: Path) -> list[CodexAssessment]:
    if not path.exists():
        return []
    return [
        CodexAssessment.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summarize_codex_assessments(
    assessments: Sequence[CodexAssessment],
) -> dict[str, Any]:
    """Per-unit rollup that never counts repeated passes as independent."""
    by_unit: dict[tuple[str, str], list[CodexAssessment]] = defaultdict(list)
    for item in assessments:
        by_unit[(item.document_key, item.unit_id)].append(item)

    units = []
    questions: dict[str, set[str]] = defaultdict(set)
    for (document, unit_id), items in sorted(by_unit.items()):
        axis_values: dict[str, set[str]] = defaultdict(set)
        for item in items:
            for axis in item.axes:
                if axis.judgment.state == "labeled":
                    axis_values[axis.judgment.axis_id].add(
                        json.dumps(axis.judgment.value)
                    )
            for question in item.policy_questions:
                questions[question.question].update(question.axis_ids)
        units.append(
            {
                "document_key": document,
                "unit_id": unit_id,
                "pass_count": len(items),
                "independent_judgment_count": 1,
                "axes_with_pass_disagreement": sorted(
                    axis for axis, values in axis_values.items() if len(values) > 1
                ),
            }
        )
    return {
        "tier": "quarantined",
        "note": (
            "Passes share one model family and saw Jev output; agreement is "
            "correlated evidence, not independent confirmation."
        ),
        "unit_count": len(units),
        "assessment_count": len(assessments),
        "units": units,
        "policy_questions": [
            {"question": q, "axis_ids": sorted(axes)}
            for q, axes in sorted(questions.items())
        ],
    }


def _jev_axis_value(answer: Mapping[str, Any] | None, axis_id: str) -> Any:
    """Jev's answer as an axis value, or None when it is not comparable."""
    if not answer or answer.get("status") != "complete":
        return None
    selected = answer.get("selected")
    if axis_id == "statement_type":
        return selected
    return {"yes": True, "no": False}.get(selected)


def compare_codex_to_jev(
    assessments: Sequence[CodexAssessment],
    *,
    jev_artifacts: Iterable[ShadowClassificationArtifact],
) -> dict[str, Any]:
    """Stage 2: compare blind Codex labels with Jev's answers, per pass.

    Counts stay separate per ``pass_id`` because passes are correlated; adding
    them up would overstate the evidence. Legacy v1 records are skipped since
    they saw Jev output before labeling.
    """
    units = _units_by_identity(jev_artifacts)
    passes: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(
            lambda: {"agrees": 0, "disagrees": 0, "unclear": 0, "codex_unlabeled": 0}
        )
    )
    disagreements: list[dict[str, Any]] = []
    skipped_legacy = 0
    missing_units: set[tuple[str, str]] = set()
    for item in assessments:
        if item.saw_jev_output:
            skipped_legacy += 1
            continue
        unit = units.get((item.document_key, item.unit_id))
        if unit is None:
            missing_units.add((item.document_key, item.unit_id))
            continue
        answers = _jev_answers(unit)
        for axis in item.axes:
            judgment = axis.judgment
            counts = passes[item.pass_id][judgment.axis_id]
            if judgment.state != "labeled":
                counts["codex_unlabeled"] += 1
                continue
            answer = answers.get(judgment.axis_id)
            jev_value = _jev_axis_value(answer, judgment.axis_id)
            if jev_value is None:
                counts["unclear"] += 1
            elif jev_value == judgment.value:
                counts["agrees"] += 1
            else:
                counts["disagrees"] += 1
                disagreements.append(
                    {
                        "pass_id": item.pass_id,
                        "document_key": item.document_key,
                        "unit_id": item.unit_id,
                        "axis_id": judgment.axis_id,
                        "source_text": unit.source_text,
                        "codex_value": judgment.value,
                        "codex_rationale": judgment.rationale,
                        "jev_value": jev_value,
                        "jev_raw_probability": answer.get("raw_probability") if answer else None,
                        "import_flags": item.import_flags,
                    }
                )
    return {
        "schema_version": CODEX_COMPARISON_SCHEMA_VERSION,
        "tier": "quarantined",
        "note": (
            "Codex labeled blind; counts are per pass and passes are correlated. "
            "Agreement is not confirmation and disagreement is not a Jev error."
        ),
        "skipped_legacy_v1": skipped_legacy,
        "missing_units": [
            {"document_key": doc, "unit_id": unit_id}
            for doc, unit_id in sorted(missing_units)
        ],
        "passes": {
            pass_id: {axis_id: dict(counts) for axis_id, counts in sorted(axes.items())}
            for pass_id, axes in sorted(passes.items())
        },
        "disagreements": sorted(
            disagreements,
            key=lambda d: (d["pass_id"], d["axis_id"], d["document_key"], d["unit_id"]),
        ),
    }
