"""Quarantine-only import of Codex assessments of Jev decision outputs.

Assessments produced by an interactive Codex session outside the API-routed
harness carry no verified call provenance, saw Jev's outputs, and share one
model family across passes. They therefore get their own record type: it cannot
be read as an ``AgentReference`` or ``AgentJudgment``, carries no approval
trace, and its tier, independence, and promotion flags are fixed literals that
validation refuses to change. Repeated passes are correlated evidence and are
summarized as a single independent judgment per unit.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AxisJudgment,
)
from research_analysis_layer.evals.decision_reviews import sha256_text
from research_analysis_layer.models.decision_models import ShadowClassificationArtifact

CODEX_ASSESSMENT_SCHEMA_VERSION = "decision-codex-assessment-v1"
QUARANTINE_FILENAME = "codex_assessments.jsonl"
CORRELATION_GROUP = "codex"
# Directories holding human-reviewed records; quarantine output never goes there.
_PROTECTED_MARKERS = ("reviews.jsonl",)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodexAxisAssessment(StrictModel):
    """Codex's sparse label for one axis plus its view of Jev's answer."""

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

    schema_version: Literal["decision-codex-assessment-v1"] = (
        CODEX_ASSESSMENT_SCHEMA_VERSION
    )
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

    # Fixed by construction; any other value fails validation.
    tier: Literal["quarantined"] = "quarantined"
    review_state: Literal["provisional"] = "provisional"
    correlation_group: Literal["codex"] = CORRELATION_GROUP
    saw_jev_output: Literal[True] = True
    provenance_verified: Literal[False] = False
    independent: Literal[False] = False
    eligible_for_promotion: Literal[False] = False

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
    output_path: str


def _unit_identities(
    artifacts: Iterable[ShadowClassificationArtifact],
) -> dict[tuple[str, str], str]:
    identities: dict[tuple[str, str], str] = {}
    for artifact in artifacts:
        for unit in artifact.units:
            document = unit.document_key or artifact.document_key
            if not document:
                continue
            identities[(document, unit.unit_id)] = sha256_text(unit.source_text)
    return identities


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
) -> CodexImportResult:
    """Validate and append assessments to the quarantine file.

    Per-record problems are reported in ``rejected`` and do not stop valid
    records. Existing lines are never rewritten.
    """
    _check_quarantine_dir(quarantine_dir)
    identities = _unit_identities(jev_artifacts)
    output_path = quarantine_dir / QUARANTINE_FILENAME
    seen = _existing_ids(output_path)

    accepted: list[CodexAssessment] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        label = str(raw.get("assessment_id", f"record[{index}]"))
        try:
            record = CodexAssessment.model_validate(raw)
        except ValueError as exc:
            rejected.append({"record": label, "reason": f"schema: {exc}"})
            continue
        expected = identities.get((record.document_key, record.unit_id))
        if expected is None:
            rejected.append({"record": label, "reason": "unit not in Jev artifacts"})
        elif expected != record.source_text_sha256:
            rejected.append({"record": label, "reason": "source text hash mismatch"})
        elif record.assessment_id in seen:
            rejected.append({"record": label, "reason": "duplicate assessment_id"})
        else:
            seen.add(record.assessment_id)
            accepted.append(record)

    if accepted:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as handle:
            for record in accepted:
                handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True))
                handle.write("\n")
    return CodexImportResult(
        accepted=len(accepted), rejected=rejected, output_path=str(output_path)
    )


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
