"""Contracts for agent-reviewed decision-classification references.

Agent-reviewed references are intentionally separate from human gold.  They
cannot carry a human approval trace and they never use the human ``agreed``
lifecycle.  Labels are sparse per axis: omitted axes are unknown, not false.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_analysis_layer.evals.decision_reviews import (
    NOUL_QUESTION_IDS,
    SourceArtifactReference,
    sha256_text,
)

AGENT_REFERENCE_SCHEMA_VERSION = "decision-agent-reference-v1"
AGENT_JUDGMENT_SCHEMA_VERSION = "decision-agent-judgment-v1"
POLICY_ESCALATION_SCHEMA_VERSION = "decision-policy-escalation-v1"
ROLE_PROMPT_VERSION = "decision-reference-role-v1"

StatementType = Literal[
    "assertion",
    "evidence_report",
    "question",
    "recommendation",
    "background_methodology",
    "other_or_unclear",
]
AxisId = Literal[
    "statement_type",
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
AXIS_IDS: tuple[str, ...] = ("statement_type", *NOUL_QUESTION_IDS)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceTransformation(StrictModel):
    transformation_id: str = Field(min_length=1)
    kind: Literal[
        "none",
        "heading_removed",
        "neighbor_removed",
        "formatting_only",
        "normalized_whitespace",
        "other",
    ]
    description: str = Field(min_length=1)
    meaning_preserved: bool | None = None


class AgentReferenceSource(StrictModel):
    """Frozen source scope for one independently labeled unit."""

    source_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_type: str | None = None
    unit_id: str = Field(min_length=1)
    source_lineage_id: str = Field(min_length=1)
    split: Literal["development", "qualification", "held_out"]
    source_text: str = Field(min_length=1)
    source_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_text: str = Field(min_length=1)
    target_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_start: int = Field(ge=0)
    target_end: int = Field(gt=0)
    normalized_text: str | None = None
    surrounding_context: str | None = None
    stored_model_input: str | None = None
    transformations: list[SourceTransformation] = Field(default_factory=list)
    source_artifact: SourceArtifactReference

    @model_validator(mode="after")
    def _validate_source_scope(self) -> AgentReferenceSource:
        if self.source_text_sha256 != sha256_text(self.source_text):
            raise ValueError("source_text_sha256 does not match source_text")
        if self.target_text_sha256 != sha256_text(self.target_text):
            raise ValueError("target_text_sha256 does not match target_text")
        if self.target_end > len(self.source_text):
            raise ValueError("target offsets exceed source_text")
        if self.target_start >= self.target_end:
            raise ValueError("target_start must be before target_end")
        if self.source_text[self.target_start : self.target_end] != self.target_text:
            raise ValueError("target offsets do not select target_text")
        transformation_ids = [item.transformation_id for item in self.transformations]
        if len(transformation_ids) != len(set(transformation_ids)):
            raise ValueError("source transformation IDs must be unique")
        return self

    @property
    def source_key(self) -> tuple[str, str, str]:
        return (self.document_id, self.unit_id, self.target_text_sha256)


class SupportingSpan(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> SupportingSpan:
        if self.start >= self.end:
            raise ValueError("supporting span start must be before end")
        return self


class AxisJudgment(StrictModel):
    """One role's sparse judgment for an axis."""

    axis_id: AxisId
    state: Literal["labeled", "unresolved", "abstained"]
    value: StatementType | bool | None = None
    rationale: str = Field(min_length=1)
    supporting_spans: list[SupportingSpan] = Field(default_factory=list)
    unresolved_reason: str | None = None

    @model_validator(mode="after")
    def _validate_axis_value(self) -> AxisJudgment:
        if self.state == "labeled":
            if self.value is None:
                raise ValueError("labeled axes require a value")
            if self.unresolved_reason is not None:
                raise ValueError("labeled axes cannot have unresolved_reason")
            if self.axis_id == "statement_type":
                if type(self.value) is not str:
                    raise ValueError("statement_type requires a statement-type value")
            elif type(self.value) is not bool:
                raise ValueError("Noul axes require JSON boolean values")
        else:
            if self.value is not None:
                raise ValueError("unresolved or abstained axes cannot carry a value")
            if not self.unresolved_reason:
                raise ValueError(
                    "unresolved or abstained axes require unresolved_reason"
                )
        return self


class ModelIdentity(StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    resolved_version: str = Field(min_length=1)


class CallUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_usd: float | None = Field(default=None, ge=0)


class AgentJudgment(StrictModel):
    """Immutable output from annotator, reviewer, adjudicator, or auditor."""

    schema_version: Literal[
        "decision-agent-judgment-v1"
    ] = AGENT_JUDGMENT_SCHEMA_VERSION
    judgment_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    role: Literal["annotator", "reviewer", "adjudicator", "auditor"]
    pass_kind: Literal["blind_first_pass", "comparison"]
    model: ModelIdentity
    role_prompt_version: str = ROLE_PROMPT_VERSION
    role_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_version: str = Field(min_length=1)
    taxonomy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_id: str = Field(min_length=1)
    created_at: datetime
    sampling: dict[str, Any] = Field(default_factory=dict)
    usage: CallUsage = Field(default_factory=CallUsage)
    axes: list[AxisJudgment]

    @field_validator("axes")
    @classmethod
    def _unique_axes(cls, value: list[AxisJudgment]) -> list[AxisJudgment]:
        axis_ids = [axis.axis_id for axis in value]
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("a judgment cannot repeat an axis")
        return value

    @model_validator(mode="after")
    def _blind_first_pass_roles(self) -> AgentJudgment:
        if self.role in {"annotator", "reviewer"} and self.pass_kind != "blind_first_pass":
            raise ValueError("annotator and reviewer outputs must be blind first passes")
        return self

    def labeled_value(self, axis_id: str) -> StatementType | bool | None:
        for axis in self.axes:
            if axis.axis_id == axis_id and axis.state == "labeled":
                return axis.value
        return None

    def validate_spans(self, source: AgentReferenceSource) -> None:
        if self.source_id != source.source_id:
            raise ValueError("judgment source_id does not match source")
        for axis in self.axes:
            for span in axis.supporting_spans:
                if span.end > len(source.target_text):
                    raise ValueError(
                        f"supporting span exceeds target_text for {axis.axis_id}"
                    )
                if source.target_text[span.start : span.end] != span.text:
                    raise ValueError(
                        f"supporting span text mismatch for {axis.axis_id}"
                    )


class AcceptedAxis(StrictModel):
    axis_id: AxisId
    value: StatementType | bool
    tier: Literal["provisional", "qualified"]
    supporting_judgment_ids: list[str] = Field(min_length=2)
    gate_version: str = Field(min_length=1)
    admission_reason: str = Field(min_length=1)
    correlated_models: bool
    qualification_report_id: str | None = None

    @field_validator("supporting_judgment_ids")
    @classmethod
    def _unique_support(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("supporting judgment IDs must be unique")
        return value

    @model_validator(mode="after")
    def _qualified_has_evidence(self) -> AcceptedAxis:
        if self.axis_id == "statement_type":
            if type(self.value) is not str:
                raise ValueError("statement_type requires a statement-type value")
        elif type(self.value) is not bool:
            raise ValueError("Noul axes require JSON boolean values")
        if self.tier == "qualified" and not self.qualification_report_id:
            raise ValueError("qualified axes require qualification_report_id")
        if self.tier == "provisional" and self.qualification_report_id is not None:
            raise ValueError(
                "provisional axes cannot claim a qualification_report_id"
            )
        return self


class AgentReferenceRecord(StrictModel):
    """Sparse accepted labels with reconstructable independent evidence."""

    schema_version: Literal[
        "decision-agent-reference-v1"
    ] = AGENT_REFERENCE_SCHEMA_VERSION
    reference_id: str = Field(min_length=1)
    source: AgentReferenceSource
    judgments: list[AgentJudgment] = Field(min_length=2)
    accepted_axes: list[AcceptedAxis] = Field(default_factory=list)
    quarantined_axes: dict[str, str] = Field(default_factory=dict)
    lifecycle: Literal[
        "provisional", "qualified", "quarantined", "superseded", "retired"
    ]
    release_id: str | None = None
    supersedes_reference_id: str | None = None
    retirement_reason: str | None = None

    @field_validator("accepted_axes")
    @classmethod
    def _unique_accepted_axes(cls, value: list[AcceptedAxis]) -> list[AcceptedAxis]:
        axis_ids = [axis.axis_id for axis in value]
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("accepted_axes cannot repeat an axis")
        return value

    @field_validator("quarantined_axes")
    @classmethod
    def _known_quarantine_axes(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(AXIS_IDS))
        if unknown:
            raise ValueError(f"quarantined_axes contains unknown axes: {unknown}")
        if any(not reason.strip() for reason in value.values()):
            raise ValueError("quarantined axes require a reason")
        return value

    @model_validator(mode="after")
    def _validate_reference(self) -> AgentReferenceRecord:
        judgment_ids = [judgment.judgment_id for judgment in self.judgments]
        if len(judgment_ids) != len(set(judgment_ids)):
            raise ValueError("judgment IDs must be unique")
        call_ids = [judgment.call_id for judgment in self.judgments]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("independent judgments cannot reuse a call_id")
        for judgment in self.judgments:
            judgment.validate_spans(self.source)

        accepted_ids = {axis.axis_id for axis in self.accepted_axes}
        overlap = sorted(accepted_ids & set(self.quarantined_axes))
        if overlap:
            raise ValueError(f"axes cannot be accepted and quarantined: {overlap}")

        by_id = {judgment.judgment_id: judgment for judgment in self.judgments}
        for accepted in self.accepted_axes:
            supporters: list[AgentJudgment] = []
            for judgment_id in accepted.supporting_judgment_ids:
                judgment = by_id.get(judgment_id)
                if judgment is None:
                    raise ValueError(
                        f"accepted axis references unknown judgment {judgment_id!r}"
                    )
                if judgment.pass_kind != "blind_first_pass":
                    raise ValueError(
                        "accepted axes require two blind first-pass judgments"
                    )
                if judgment.role not in {"annotator", "reviewer"}:
                    raise ValueError(
                        "accepted axes require annotator and reviewer support"
                    )
                if judgment.labeled_value(accepted.axis_id) != accepted.value:
                    raise ValueError(
                        f"supporting judgment disagrees on {accepted.axis_id}"
                    )
                supporters.append(judgment)
            if {judgment.role for judgment in supporters} != {"annotator", "reviewer"}:
                raise ValueError(
                    "accepted axes require support from both annotator and reviewer"
                )
            families = {judgment.model.model_family for judgment in supporters}
            actually_correlated = len(families) == 1
            if actually_correlated != accepted.correlated_models:
                raise ValueError(
                    "correlated_models must reflect supporting model families"
                )

        has_qualified = any(axis.tier == "qualified" for axis in self.accepted_axes)
        if self.lifecycle == "qualified" and not has_qualified:
            raise ValueError("qualified records require at least one qualified axis")
        if self.lifecycle in {"provisional", "qualified"} and not self.accepted_axes:
            raise ValueError("accepted record lifecycles require accepted_axes")
        if self.lifecycle == "quarantined" and self.accepted_axes:
            raise ValueError("fully quarantined records cannot carry accepted axes")
        if self.lifecycle == "retired" and not self.retirement_reason:
            raise ValueError("retired records require retirement_reason")
        if self.lifecycle != "retired" and self.retirement_reason is not None:
            raise ValueError("retirement_reason is valid only for retired records")
        if self.supersedes_reference_id == self.reference_id:
            raise ValueError("a reference cannot supersede itself")
        return self

    @property
    def omitted_axis_ids(self) -> list[str]:
        present = {axis.axis_id for axis in self.accepted_axes} | set(
            self.quarantined_axes
        )
        return [axis_id for axis_id in AXIS_IDS if axis_id not in present]


class ReferenceLabelView(StrictModel):
    reference_id: str
    document_id: str
    unit_id: str
    statement_type: StatementType | None = None
    noul_labels: dict[str, bool] = Field(default_factory=dict)
    tiers: dict[str, Literal["provisional", "qualified"]]


def reference_label_views(
    records: Iterable[AgentReferenceRecord],
    *,
    minimum_tier: Literal["provisional", "qualified"] = "provisional",
) -> list[ReferenceLabelView]:
    """Adapt accepted sparse axes for separate agent-reference evaluation."""

    views: list[ReferenceLabelView] = []
    for record in records:
        statement_type: StatementType | None = None
        noul_labels: dict[str, bool] = {}
        tiers: dict[str, Literal["provisional", "qualified"]] = {}
        for axis in record.accepted_axes:
            if minimum_tier == "qualified" and axis.tier != "qualified":
                continue
            tiers[axis.axis_id] = axis.tier
            if axis.axis_id == "statement_type":
                statement_type = axis.value  # type: ignore[assignment]
            else:
                noul_labels[axis.axis_id] = axis.value  # type: ignore[assignment]
        if tiers:
            views.append(
                ReferenceLabelView(
                    reference_id=record.reference_id,
                    document_id=record.source.document_id,
                    unit_id=record.source.unit_id,
                    statement_type=statement_type,
                    noul_labels=noul_labels,
                    tiers=tiers,
                )
            )
    return views


def load_agent_references(path: Path) -> list[AgentReferenceRecord]:
    """Load a JSONL reference collection without collapsing its evidence."""

    records: list[AgentReferenceRecord] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = AgentReferenceRecord.model_validate_json(raw_line)
        except Exception as exc:
            raise ValueError(
                f"invalid agent-reference line {line_number}: {exc}"
            ) from exc
        if record.reference_id in seen_ids:
            raise ValueError(f"duplicate reference_id {record.reference_id!r}")
        seen_ids.add(record.reference_id)
        records.append(record)
    return records


class EscalationExample(StrictModel):
    case_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class PolicyEscalation(StrictModel):
    """One root policy question eligible for exceptional human escalation."""

    schema_version: Literal[
        "decision-policy-escalation-v1"
    ] = POLICY_ESCALATION_SCHEMA_VERSION
    escalation_id: str = Field(min_length=1)
    policy_key: str = Field(min_length=1)
    status: Literal["pending", "resolved", "superseded"]
    question: str = Field(min_length=1)
    affected_axes: list[AxisId] = Field(min_length=1)
    case_ids: list[str] = Field(min_length=1)
    impact_count: int = Field(ge=1)
    examples: list[EscalationExample] = Field(min_length=1, max_length=2)
    interpretations: list[str] = Field(min_length=2, max_length=3)
    recommendation: str = Field(min_length=1)
    recommendation_evidence: str = Field(min_length=1)
    proceed_while_pending: str = Field(min_length=1)
    first_seen_at: datetime
    evidence_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_notified_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    resolution: str | None = None
    resolution_provenance: str | None = None
    superseded_by: str | None = None

    @field_validator("affected_axes", "case_ids")
    @classmethod
    def _unique_lists(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("escalation axes and case IDs must be unique")
        return value

    @model_validator(mode="after")
    def _validate_escalation(self) -> PolicyEscalation:
        if self.impact_count < len(self.case_ids):
            raise ValueError("impact_count cannot be smaller than case_ids")
        if self.status == "resolved":
            if not self.resolution or not self.resolution_provenance:
                raise ValueError(
                    "resolved escalations require resolution and provenance"
                )
        elif self.resolution is not None or self.resolution_provenance is not None:
            raise ValueError("only resolved escalations may carry a resolution")
        if self.status == "superseded" and not self.superseded_by:
            raise ValueError("superseded escalations require superseded_by")
        if self.status != "superseded" and self.superseded_by is not None:
            raise ValueError("superseded_by is valid only for superseded escalations")
        return self

    @property
    def notification_due(self) -> bool:
        return (
            self.status == "pending"
            and self.evidence_fingerprint != self.last_notified_fingerprint
        )


def escalation_packet(
    escalations: Iterable[PolicyEscalation], *, max_questions: int = 3
) -> list[PolicyEscalation]:
    """Return at most three changed pending policy questions for notification."""

    if not 1 <= max_questions <= 3:
        raise ValueError("max_questions must be between 1 and 3")
    pending = [item for item in escalations if item.notification_due]
    return sorted(
        pending,
        key=lambda item: (-item.impact_count, item.first_seen_at, item.policy_key),
    )[:max_questions]


def load_policy_escalations(path: Path) -> list[PolicyEscalation]:
    """Load and validate a JSONL policy register."""

    records: list[PolicyEscalation] = []
    seen_ids: set[str] = set()
    seen_policy_versions: set[tuple[str, str]] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = PolicyEscalation.model_validate_json(raw_line)
        except Exception as exc:
            raise ValueError(f"invalid policy register line {line_number}: {exc}") from exc
        if record.escalation_id in seen_ids:
            raise ValueError(f"duplicate escalation_id {record.escalation_id!r}")
        version_key = (record.policy_key, record.evidence_fingerprint)
        if version_key in seen_policy_versions:
            raise ValueError(
                "duplicate policy_key/evidence_fingerprint in policy register: "
                f"{record.policy_key!r}"
            )
        seen_ids.add(record.escalation_id)
        seen_policy_versions.add(version_key)
        records.append(record)
    return records


def role_prompt_path(role: Literal["annotator", "reviewer", "curator"]) -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "prompts"
        / "evals"
        / "decision_references"
        / f"{role}.md"
    )


def role_prompt_sha256(role: Literal["annotator", "reviewer", "curator"]) -> str:
    return hashlib.sha256(role_prompt_path(role).read_bytes()).hexdigest()


def canonical_record_hash(record: BaseModel) -> str:
    payload = record.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "AGENT_JUDGMENT_SCHEMA_VERSION",
    "AGENT_REFERENCE_SCHEMA_VERSION",
    "AXIS_IDS",
    "AgentJudgment",
    "AgentReferenceRecord",
    "AgentReferenceSource",
    "AcceptedAxis",
    "AxisJudgment",
    "CallUsage",
    "EscalationExample",
    "ModelIdentity",
    "POLICY_ESCALATION_SCHEMA_VERSION",
    "PolicyEscalation",
    "ReferenceLabelView",
    "ROLE_PROMPT_VERSION",
    "SourceTransformation",
    "SupportingSpan",
    "canonical_record_hash",
    "escalation_packet",
    "load_policy_escalations",
    "load_agent_references",
    "reference_label_views",
    "role_prompt_path",
    "role_prompt_sha256",
]
