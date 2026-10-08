"""Versioned review records and release preparation for decision-model gold.

This module deliberately separates review history from runtime classification.
It can prepare a proposed release, but it cannot turn a candidate into an
agreed record or alter production routing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_analysis_layer.evals.decision_artifacts import load_shadow_artifact
from research_analysis_layer.models.decision_models import (
    SUBTYPE_NOUL_IDS,
    SUPPORT_NOUL_IDS,
)

REVIEW_RECORD_SCHEMA_VERSION = "decision-review-record-v2"
RELEASE_MANIFEST_SCHEMA_VERSION = "decision-gold-release-manifest-v1"
NOUL_QUESTION_IDS: tuple[str, ...] = (*SUBTYPE_NOUL_IDS, *SUPPORT_NOUL_IDS)
ReviewStatus = Literal["candidate", "agreed", "superseded", "retired"]
LabelCompleteness = Literal["complete", "partial"]
SignalId = Literal[
    "is_observation",
    "is_forecast",
    "is_causal",
    "is_market_impact",
    "is_policy_claim",
    "is_risk_or_scenario",
    "is_comparative",
    "is_trade_or_action",
    "contains_verifiable_evidence",
    "contains_reasoning_bridge",
    "is_substantive_author_claim",
]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceArtifactReference(StrictModel):
    """Immutable pointer to the shadow artifact that contains the model input."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def _relative_path_only(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("source artifact path must be relative and cannot traverse")
        return path.as_posix()


class ApprovalTrace(StrictModel):
    """Existing or new human approval evidence, stored independently of labels."""

    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note_reference: str = Field(min_length=1)

    @field_validator("source_path")
    @classmethod
    def _relative_path_only(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("approval source path must be relative and cannot traverse")
        return path.as_posix()


class ReviewedLabels(StrictModel):
    """Human judgment for the current decision question set.

    ``noul_labels`` may contain any subset of the recognized binary questions.
    Omitted keys are unreviewed — never stored as false, never inferred.
    """

    statement_type: Literal[
        "assertion",
        "evidence_report",
        "question",
        "recommendation",
        "background_methodology",
        "other_or_unclear",
    ]
    noul_labels: dict[str, bool] = Field(default_factory=dict)

    @field_validator("noul_labels", mode="before")
    @classmethod
    def _binary_labels_are_booleans(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("noul_labels must be an object")
        null_keys = sorted(
            str(question_id) for question_id, label in value.items() if label is None
        )
        if null_keys:
            raise ValueError(
                "omitted Noul labels must be absent, not null: "
                f"null_keys={null_keys}"
            )
        non_boolean = sorted(
            str(question_id)
            for question_id, label in value.items()
            if type(label) is not bool
        )
        if non_boolean:
            raise ValueError(
                "noul_labels values must be JSON booleans: "
                f"non_boolean={non_boolean}"
            )
        return value

    @field_validator("noul_labels")
    @classmethod
    def _recognized_binary_signals_only(cls, value: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(set(value) - set(NOUL_QUESTION_IDS))
        if unknown:
            raise ValueError(f"noul_labels contains unknown question ids: {unknown}")
        return {
            question_id: bool(value[question_id])
            for question_id in NOUL_QUESTION_IDS
            if question_id in value
        }

    @property
    def unreviewed_noul_ids(self) -> list[str]:
        return [question_id for question_id in NOUL_QUESTION_IDS if question_id not in self.noul_labels]

    @property
    def label_completeness(self) -> LabelCompleteness:
        return "complete" if not self.unreviewed_noul_ids else "partial"


class DecisionReviewRecord(StrictModel):
    """One immutable adjudication event for a source unit and taxonomy version."""

    schema_version: Literal["decision-review-record-v2"] = REVIEW_RECORD_SCHEMA_VERSION
    review_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_type: str | None = None
    unit_id: str = Field(min_length=1)
    reviewed_text: str = Field(min_length=1)
    reviewed_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stored_model_input: str | None = None
    stored_model_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    question_set_version: str = Field(min_length=1)
    question_set_content_hash: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    labels: ReviewedLabels
    label_completeness: LabelCompleteness | None = None
    unreviewed_noul_ids: list[str] | None = None
    dominant_signals: list[SignalId] = Field(default_factory=list)
    secondary_signals: list[SignalId] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)
    review_date: date
    status: ReviewStatus
    rationale: str = Field(min_length=1)
    issue_tags: list[str] = Field(default_factory=list)
    source_artifact: SourceArtifactReference
    approval_trace: ApprovalTrace | None = None
    supersedes_review_id: str | None = None
    retirement_reason: str | None = None

    @field_validator("dominant_signals", "secondary_signals")
    @classmethod
    def _signals_are_unique(cls, value: list[SignalId]) -> list[SignalId]:
        if len(value) != len(set(value)):
            raise ValueError("signal annotations cannot contain duplicates")
        return value

    @field_validator("issue_tags")
    @classmethod
    def _tags_are_normalized(cls, value: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in value]
        if any(not tag for tag in normalized):
            raise ValueError("issue tags cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("issue tags cannot contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _validate_record(self) -> DecisionReviewRecord:
        if self.reviewed_text_sha256 != sha256_text(self.reviewed_text):
            raise ValueError("reviewed_text_sha256 does not match reviewed_text")

        model_input = self.stored_model_input or self.reviewed_text
        if self.stored_model_input_sha256 != sha256_text(model_input):
            raise ValueError(
                "stored_model_input_sha256 does not match the stored model input"
            )
        if self.reviewed_text not in model_input:
            raise ValueError("reviewed_text must be contained in the stored model input")

        overlap = sorted(set(self.dominant_signals) & set(self.secondary_signals))
        if overlap:
            raise ValueError(f"dominant and secondary signals overlap: {overlap}")

        if self.status == "agreed" and self.approval_trace is None:
            raise ValueError("agreed records require an approval_trace")
        if self.status == "candidate" and self.approval_trace is not None:
            raise ValueError("candidate records cannot carry an approval_trace")
        if self.status == "retired" and not self.retirement_reason:
            raise ValueError("retired records require a retirement_reason")
        if self.status != "retired" and self.retirement_reason is not None:
            raise ValueError("retirement_reason is only valid for retired records")
        if self.supersedes_review_id == self.review_id:
            raise ValueError("a review record cannot supersede itself")

        expected_unreviewed = self.labels.unreviewed_noul_ids
        expected_completeness = self.labels.label_completeness
        if self.unreviewed_noul_ids is None:
            self.unreviewed_noul_ids = expected_unreviewed
        elif list(self.unreviewed_noul_ids) != expected_unreviewed:
            raise ValueError(
                "unreviewed_noul_ids must match omitted recognized Noul keys; "
                "missing labels are unknown, not false"
            )
        if self.label_completeness is None:
            self.label_completeness = expected_completeness
        elif self.label_completeness != expected_completeness:
            raise ValueError(
                "label_completeness must be 'complete' iff every recognized Noul "
                f"is reviewed; expected {expected_completeness!r}"
            )
        return self

    @property
    def model_input(self) -> str:
        return self.stored_model_input or self.reviewed_text

    @property
    def unit_version_key(self) -> tuple[str, str, str]:
        return (self.document_id, self.unit_id, self.question_set_version)


class ValidationIssue(StrictModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    review_id: str | None = None


class ReviewValidationReport(StrictModel):
    valid: bool
    sources_verified: bool
    record_count: int
    agreed_count: int
    candidate_count: int
    history_count: int
    issues: list[ValidationIssue] = Field(default_factory=list)


def default_review_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "evals" / "decision_reviews"


def default_review_records_path() -> Path:
    return default_review_dir() / "reviews.jsonl"


def load_review_records(path: Path) -> list[DecisionReviewRecord]:
    """Load review records from either a JSON array or JSONL file."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(rows, list):
        raise ValueError("review record file must contain a JSON array or JSONL rows")
    return [DecisionReviewRecord.model_validate(row) for row in rows]


def gold_labels_from_review_records(
    records: Sequence[DecisionReviewRecord],
    *,
    require_complete: bool = False,
) -> list[Any]:
    """Project agreed reviews into gold labels.

    Partial records are included unless ``require_complete`` is true. Callers
    that need a full Noul vector must pass ``require_complete=True``.
    """
    from research_analysis_layer.evals.decision_metrics import GoldUnitLabel

    labels: list[GoldUnitLabel] = []
    for record in records:
        if record.status != "agreed":
            continue
        if require_complete and record.label_completeness != "complete":
            continue
        labels.append(
            GoldUnitLabel(
                unit_id=record.unit_id,
                document_id=record.document_id,
                statement_type=record.labels.statement_type,
                noul_labels=dict(record.labels.noul_labels),
                notes=(
                    "partial-label review; unreviewed Nouls omitted"
                    if record.label_completeness == "partial"
                    else record.rationale
                ),
            )
        )
    return labels


def validate_review_records(
    records: Sequence[DecisionReviewRecord],
    *,
    artifact_root: Path | None = None,
) -> ReviewValidationReport:
    """Validate lifecycle invariants and, when available, immutable sources."""
    issues: list[ValidationIssue] = []
    by_id: dict[str, DecisionReviewRecord] = {}
    id_counts = Counter(record.review_id for record in records)
    for review_id, count in sorted(id_counts.items()):
        if count > 1:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="duplicate_review_id",
                    review_id=review_id,
                    message=f"review_id occurs {count} times",
                )
            )
    for record in records:
        by_id.setdefault(record.review_id, record)

    active = [record for record in records if record.status in {"candidate", "agreed"}]
    active_keys = Counter(record.unit_version_key for record in active)
    for key, count in sorted(active_keys.items()):
        if count > 1:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="duplicate_active_unit_version",
                    message=(
                        f"{key[0]}/{key[1]} at {key[2]} has {count} active records; "
                        "supersede or retire the prior record"
                    ),
                )
            )

    for record in records:
        if record.supersedes_review_id is not None:
            prior = by_id.get(record.supersedes_review_id)
            if prior is None:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="missing_superseded_review",
                        review_id=record.review_id,
                        message=(
                            f"supersedes unknown review_id {record.supersedes_review_id!r}"
                        ),
                    )
                )
            elif prior.unit_version_key != record.unit_version_key:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="superseded_unit_mismatch",
                        review_id=record.review_id,
                        message="superseded record has a different document/unit/version key",
                    )
                )
            elif prior.status != "superseded":
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="superseded_status_not_preserved",
                        review_id=record.review_id,
                        message=(
                            f"prior record {prior.review_id!r} must be retained with "
                            "status='superseded'"
                        ),
                    )
                )

        if artifact_root is not None:
            issues.extend(_validate_record_sources(record, artifact_root))

    if artifact_root is None and records:
        issues.append(
            ValidationIssue(
                level="warning",
                code="artifact_validation_skipped",
                message="no artifact root supplied; source and approval drift were not checked",
            )
        )

    errors = [issue for issue in issues if issue.level == "error"]
    return ReviewValidationReport(
        valid=not errors,
        sources_verified=artifact_root is not None or not records,
        record_count=len(records),
        agreed_count=sum(record.status == "agreed" for record in records),
        candidate_count=sum(record.status == "candidate" for record in records),
        history_count=sum(record.status in {"superseded", "retired"} for record in records),
        issues=issues,
    )


def _safe_source_path(root: Path, relative: str) -> Path | None:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return None
    return candidate


def _validate_record_sources(
    record: DecisionReviewRecord,
    artifact_root: Path,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    artifact_path = _safe_source_path(artifact_root, record.source_artifact.path)
    if artifact_path is None:
        return [
            ValidationIssue(
                level="error",
                code="artifact_path_escape",
                review_id=record.review_id,
                message="source artifact resolves outside artifact root",
            )
        ]
    if not artifact_path.is_file():
        return [
            ValidationIssue(
                level="error",
                code="artifact_missing",
                review_id=record.review_id,
                message=f"source artifact not found: {record.source_artifact.path}",
            )
        ]

    actual_hash = sha256_bytes(artifact_path.read_bytes())
    if actual_hash != record.source_artifact.sha256:
        issues.append(
            ValidationIssue(
                level="error",
                code="artifact_hash_drift",
                review_id=record.review_id,
                message=(
                    f"artifact hash changed: expected {record.source_artifact.sha256}, "
                    f"found {actual_hash}"
                ),
            )
        )
        return issues

    try:
        artifact = load_shadow_artifact(artifact_path)
    except Exception as exc:  # Pydantic/JSON error is reported as input validation.
        issues.append(
            ValidationIssue(
                level="error",
                code="artifact_invalid",
                review_id=record.review_id,
                message=f"source artifact cannot be loaded: {exc}",
            )
        )
        return issues

    if artifact.document_key != record.document_id:
        issues.append(
            ValidationIssue(
                level="error",
                code="document_id_drift",
                review_id=record.review_id,
                message=(
                    f"record document_id={record.document_id!r}, "
                    f"artifact document_key={artifact.document_key!r}"
                ),
            )
        )
    unit = next((item for item in artifact.units if item.unit_id == record.unit_id), None)
    if unit is None:
        issues.append(
            ValidationIssue(
                level="error",
                code="unit_missing",
                review_id=record.review_id,
                message=f"unit {record.unit_id!r} is not present in the artifact",
            )
        )
    elif unit.source_text != record.model_input:
        issues.append(
            ValidationIssue(
                level="error",
                code="source_text_drift",
                review_id=record.review_id,
                message="stored model input no longer matches the artifact unit source text",
            )
        )

    if artifact.question_set_version != record.question_set_version:
        issues.append(
            ValidationIssue(
                level="error",
                code="question_set_version_drift",
                review_id=record.review_id,
                message=(
                    f"record uses {record.question_set_version!r}; artifact uses "
                    f"{artifact.question_set_version!r}"
                ),
            )
        )
    if artifact.question_set is None:
        issues.append(
            ValidationIssue(
                level="error",
                code="question_set_snapshot_missing",
                review_id=record.review_id,
                message="artifact does not contain a frozen question-set snapshot",
            )
        )
    elif artifact.question_set.content_hash != record.question_set_content_hash:
        issues.append(
            ValidationIssue(
                level="error",
                code="question_set_hash_drift",
                review_id=record.review_id,
                message=(
                    f"record uses {record.question_set_content_hash!r}; artifact uses "
                    f"{artifact.question_set.content_hash!r}"
                ),
            )
        )

    for field_name in ("provider", "model_version", "adapter_version"):
        actual = getattr(artifact, field_name)
        expected = getattr(record, field_name)
        if actual != expected:
            issues.append(
                ValidationIssue(
                    level="error",
                    code=f"{field_name}_drift",
                    review_id=record.review_id,
                    message=f"record uses {expected!r}; artifact uses {actual!r}",
                )
            )

    if record.approval_trace is not None:
        approval_path = _safe_source_path(
            artifact_root, record.approval_trace.source_path
        )
        if approval_path is None or not approval_path.is_file():
            issues.append(
                ValidationIssue(
                    level="error",
                    code="approval_source_missing",
                    review_id=record.review_id,
                    message=(
                        "approval source not found under artifact root: "
                        f"{record.approval_trace.source_path}"
                    ),
                )
            )
        else:
            approval_bytes = approval_path.read_bytes()
            approval_hash = sha256_bytes(approval_bytes)
            if approval_hash != record.approval_trace.source_sha256:
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="approval_source_hash_drift",
                        review_id=record.review_id,
                        message="approval source hash has changed",
                    )
                )
            elif record.approval_trace.note_reference not in approval_bytes.decode(
                "utf-8", errors="replace"
            ):
                issues.append(
                    ValidationIssue(
                        level="error",
                        code="approval_note_missing",
                        review_id=record.review_id,
                        message="approval note reference is absent from the approval source",
                    )
                )
    return issues


def coverage_report(records: Sequence[DecisionReviewRecord]) -> dict[str, Any]:
    """Report coverage without mixing candidates or history into gold counts."""

    def summarize(selected: Iterable[DecisionReviewRecord]) -> dict[str, Any]:
        rows = list(selected)
        noul = {}
        for question_id in NOUL_QUESTION_IDS:
            reviewed = [
                record.labels.noul_labels[question_id]
                for record in rows
                if question_id in record.labels.noul_labels
            ]
            noul[question_id] = {
                "yes": sum(reviewed),
                "no": sum(not value for value in reviewed),
                "unreviewed": len(rows) - len(reviewed),
                "reviewed": len(reviewed),
            }
        return {
            "record_count": len(rows),
            "complete_record_count": sum(
                record.label_completeness == "complete" for record in rows
            ),
            "partial_record_count": sum(
                record.label_completeness == "partial" for record in rows
            ),
            "document_count": len({record.document_id for record in rows}),
            "documents": dict(sorted(Counter(record.document_id for record in rows).items())),
            "document_types": dict(
                sorted(Counter(record.document_type or "unknown" for record in rows).items())
            ),
            "statement_types": dict(
                sorted(Counter(record.labels.statement_type for record in rows).items())
            ),
            "noul_labels": noul,
            "issue_tags": dict(
                sorted(Counter(tag for record in rows for tag in record.issue_tags).items())
            ),
        }

    return {
        "schema_version": "decision-review-coverage-v1",
        "agreed_gold": summarize(record for record in records if record.status == "agreed"),
        "candidates": summarize(record for record in records if record.status == "candidate"),
        "history_record_count": sum(
            record.status in {"superseded", "retired"} for record in records
        ),
    }


def _active_by_key(
    records: Sequence[DecisionReviewRecord],
) -> dict[tuple[str, str, str], DecisionReviewRecord]:
    return {
        record.unit_version_key: record
        for record in records
        if record.status in {"candidate", "agreed"}
    }


def change_report_markdown(
    records: Sequence[DecisionReviewRecord],
    *,
    previous: Sequence[DecisionReviewRecord] = (),
) -> str:
    """Build a stable, readable proposed-gold change report."""
    current_by_key = _active_by_key(records)
    previous_by_key = _active_by_key(previous)
    added = sorted(current_by_key.keys() - previous_by_key.keys())
    removed = sorted(previous_by_key.keys() - current_by_key.keys())
    shared = sorted(current_by_key.keys() & previous_by_key.keys())
    changed = [
        key
        for key in shared
        if _comparable_record(current_by_key[key]) != _comparable_record(previous_by_key[key])
    ]

    lines = [
        "# Decision gold change report",
        "",
        "Only records with `status=agreed` are eligible for gold metrics. "
        "Partial records keep human-agreed labels and omit unreviewed Nouls. "
        "Candidates and retained history are reported separately.",
        "",
        "## Summary",
        "",
        f"- Active additions: {len(added)}",
        f"- Active changes: {len(changed)}",
        f"- Active removals: {len(removed)}",
        f"- Agreed records after change: {sum(r.status == 'agreed' for r in records)}",
        f"- Partial agreed records: "
        f"{sum(r.status == 'agreed' and r.label_completeness == 'partial' for r in records)}",
        f"- Candidate records after change: {sum(r.status == 'candidate' for r in records)}",
        "",
    ]
    for title, keys, source in (
        ("Additions", added, current_by_key),
        ("Changes", changed, current_by_key),
        ("Removals", removed, previous_by_key),
    ):
        lines.extend([f"## {title}", ""])
        if not keys:
            lines.extend(["None.", ""])
            continue
        for key in keys:
            record = source[key]
            lines.append(
                f"- `{record.document_id}` / `{record.unit_id}` / "
                f"`{record.question_set_version}`: **{record.labels.statement_type}**, "
                f"status `{record.status}`, review `{record.review_id}`"
            )
            if title == "Changes":
                details = _change_details(previous_by_key[key], record)
                for detail in details:
                    lines.append(f"  - {detail}")
        lines.append("")
    return "\n".join(lines)


def _comparable_record(record: DecisionReviewRecord) -> dict[str, Any]:
    return {
        "status": record.status,
        "labels": record.labels.model_dump(mode="json"),
        "reviewed_text_sha256": record.reviewed_text_sha256,
        "stored_model_input_sha256": record.stored_model_input_sha256,
        "dominant_signals": record.dominant_signals,
        "secondary_signals": record.secondary_signals,
    }


def _change_details(
    previous: DecisionReviewRecord,
    current: DecisionReviewRecord,
) -> list[str]:
    details: list[str] = []
    if previous.status != current.status:
        details.append(f"Status: `{previous.status}` → `{current.status}`")
    if previous.labels.statement_type != current.labels.statement_type:
        details.append(
            "Primary type: "
            f"`{previous.labels.statement_type}` → `{current.labels.statement_type}`"
        )
    def _noul_token(labels: ReviewedLabels, question_id: str) -> str:
        if question_id not in labels.noul_labels:
            return "unreviewed"
        return "yes" if labels.noul_labels[question_id] else "no"

    for question_id in NOUL_QUESTION_IDS:
        old = _noul_token(previous.labels, question_id)
        new = _noul_token(current.labels, question_id)
        if old != new:
            details.append(f"`{question_id}`: `{old}` → `{new}`")
    if previous.reviewed_text_sha256 != current.reviewed_text_sha256:
        details.append("Reviewed text changed; migration review is required")
    elif previous.stored_model_input_sha256 != current.stored_model_input_sha256:
        details.append("Stored model input changed; source drift review is required")
    if previous.dominant_signals != current.dominant_signals:
        details.append(
            f"Dominant signals: `{previous.dominant_signals}` → "
            f"`{current.dominant_signals}`"
        )
    if previous.secondary_signals != current.secondary_signals:
        details.append(
            f"Secondary signals: `{previous.secondary_signals}` → "
            f"`{current.secondary_signals}`"
        )
    return details


def release_manifest(
    records: Sequence[DecisionReviewRecord],
    *,
    records_path: Path,
    validation: ReviewValidationReport,
    release_version: str,
) -> dict[str, Any]:
    """Describe a proposed release; this function never approves candidates."""
    agreed = sorted(
        (record for record in records if record.status == "agreed"),
        key=lambda record: (record.document_id, record.unit_id, record.review_id),
    )
    canonical = [record.model_dump(mode="json") for record in agreed]
    release_hash = sha256_text(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    )
    eligible = agreed if validation.valid and validation.sources_verified else []
    eligible_complete = [
        record for record in eligible if record.label_completeness == "complete"
    ]
    eligible_partial = [
        record for record in eligible if record.label_completeness == "partial"
    ]
    if not validation.valid:
        release_status = "invalid"
    elif not validation.sources_verified:
        release_status = "proposed_unverified"
    else:
        release_status = "proposed_valid"
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "release_version": release_version,
        "release_status": release_status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records_file": records_path.name,
        "records_file_sha256": sha256_bytes(records_path.read_bytes()),
        "agreed_record_count": len(agreed),
        "candidate_record_count": sum(record.status == "candidate" for record in records),
        "history_record_count": sum(
            record.status in {"superseded", "retired"} for record in records
        ),
        "eligible_review_ids": [record.review_id for record in eligible],
        "eligible_complete_review_ids": [record.review_id for record in eligible_complete],
        "eligible_partial_review_ids": [record.review_id for record in eligible_partial],
        "release_content_sha256": release_hash,
        "validation": validation.model_dump(mode="json"),
        "safety": {
            "candidates_excluded": True,
            "unverified_records_excluded": True,
            "partial_records_excluded_from_full_vector_metrics": True,
            "unreviewed_noul_labels_not_inferred": True,
            "production_routing_changed": False,
            "human_approval_required_for_new_or_changed_labels": True,
        },
    }


def write_release_outputs(
    *,
    records: Sequence[DecisionReviewRecord],
    records_path: Path,
    output_dir: Path,
    validation: ReviewValidationReport,
    release_version: str,
    previous: Sequence[DecisionReviewRecord] = (),
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "review_record.schema.json").write_text(
        json.dumps(DecisionReviewRecord.model_json_schema(), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "validation.json").write_text(
        json.dumps(validation.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "coverage.json").write_text(
        json.dumps(coverage_report(records), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "CHANGE_REPORT.md").write_text(
        change_report_markdown(records, previous=previous),
        encoding="utf-8",
    )
    (output_dir / "release_manifest.json").write_text(
        json.dumps(
            release_manifest(
                records,
                records_path=records_path,
                validation=validation,
                release_version=release_version,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate decision review records and prepare a proposed gold release"
    )
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Root used to verify relative shadow-artifact and approval-note paths",
    )
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--release-version",
        default=f"decision-gold-candidate-{date.today().isoformat()}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.records.is_file():
        print(f"Error: records file not found: {args.records}", file=sys.stderr)
        return 2
    try:
        records = load_review_records(args.records)
        previous = load_review_records(args.previous) if args.previous else []
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: invalid review records: {exc}", file=sys.stderr)
        return 2

    validation = validate_review_records(records, artifact_root=args.artifact_root)
    write_release_outputs(
        records=records,
        records_path=args.records,
        output_dir=args.output,
        validation=validation,
        release_version=args.release_version,
        previous=previous,
    )
    print(
        f"Validated {validation.record_count} records: "
        f"{validation.agreed_count} agreed, {validation.candidate_count} candidates"
    )
    print(f"Outputs: {args.output}")
    if not validation.valid:
        for issue in validation.issues:
            if issue.level == "error":
                print(f"ERROR [{issue.code}] {issue.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
