"""Provider-neutral decision-model contracts for shadow classification."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionKind = Literal["choice", "noul"]
DecisionStatus = Literal["complete", "uncertain", "failed", "none"]
BatchStatus = Literal["complete", "partial", "failed"]
CoverageStatus = Literal["full", "partial", "missing", "failed"]

ARTIFACT_SCHEMA_VERSION = "decision-shadow-artifact-v1"
QUESTION_SET_VERSION = "decision-question-set-v2"

STATEMENT_TYPE_OPTIONS: tuple[str, ...] = (
    "assertion",
    "evidence_report",
    "question",
    "recommendation",
    "background_methodology",
    "other_or_unclear",
)

SUBTYPE_NOUL_IDS: tuple[str, ...] = (
    "is_observation",
    "is_forecast",
    "is_causal",
    "is_market_impact",
    "is_policy_claim",
    "is_risk_or_scenario",
    "is_comparative",
    "is_trade_or_action",
)

SUPPORT_NOUL_IDS: tuple[str, ...] = (
    "contains_verifiable_evidence",
    "contains_reasoning_bridge",
    "is_substantive_author_claim",
)


class DecisionModelMetadata(BaseModel):
    """Pinned provider / adapter / question-set identity."""

    provider_name: str
    model_version: str
    question_set_version: str
    adapter_version: str


class DecisionQuestion(BaseModel):
    """One typed decision about a single target unit."""

    question_id: str
    target_unit_id: str
    question_kind: QuestionKind
    wording: str
    question_set_version: str = QUESTION_SET_VERSION
    options: list[str] | None = None
    # Optional Noul true/false criteria (provider-neutral; adapters may map).
    noul_criteria: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate_choice_options(self) -> DecisionQuestion:
        if self.question_kind == "choice":
            if not self.options:
                raise ValueError("choice questions require options")
            if self.noul_criteria:
                raise ValueError("choice questions must not supply noul_criteria")
        elif self.options:
            raise ValueError("noul questions must not supply options")
        return self


class DecisionUnit(BaseModel):
    """Source-grounded assertion unit prepared for classification."""

    unit_id: str
    text: str
    chunk_order: int
    assertion_order: int
    assertion_type: str | None = None
    section_context: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class DecisionBatch(BaseModel):
    """Bounded batch of units and independent questions sharing context."""

    batch_id: str
    shared_context: str
    units: list[DecisionUnit]
    questions: list[DecisionQuestion]
    document_key: str | None = None
    document_hash: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerDistribution(BaseModel):
    """Normalized answer mass plus selected outcome.

    Raw provider confidence is never treated as calibrated correctness.
    ``calibrated_probability`` is reserved for a later Nexus-specific fit and
    remains null in v1.
    """

    probabilities: dict[str, float]
    selected: str | None = None
    raw_probability: float | None = None
    calibrated_probability: float | None = None
    calibration_method: str | None = None
    calibration_version: str | None = None

    @field_validator("probabilities")
    @classmethod
    def _validate_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("probabilities must not be empty")
        for key, prob in value.items():
            if not isinstance(prob, (int, float)) or isinstance(prob, bool):
                raise ValueError(f"invalid probability for {key!r}")
            if prob < 0.0 or prob > 1.0:
                raise ValueError(f"probability out of range for {key!r}: {prob}")
        total = sum(float(v) for v in value.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"probabilities must sum to 1.0, got {total}")
        return {str(k): float(v) for k, v in value.items()}


class DecisionResult(BaseModel):
    """Normalized answer for one question against one unit."""

    question_id: str
    target_unit_id: str
    status: DecisionStatus
    distribution: AnswerDistribution | None = None
    raw_provider_payload: dict[str, Any] | None = None
    provider: str | None = None
    model_version: str | None = None
    error: str | None = None
    latency_ms: float | None = None
    retry_count: int = 0
    usage: dict[str, Any] = Field(default_factory=dict)


class DecisionBatchResult(BaseModel):
    """Scatter/gather outcome for one DecisionBatch."""

    batch_id: str
    status: BatchStatus
    results: list[DecisionResult]
    metadata: DecisionModelMetadata
    missing_question_ids: list[str] = Field(default_factory=list)
    unknown_question_ids: list[str] = Field(default_factory=list)
    retry_count: int = 0
    latency_ms: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_error: str | None = None


class UnitClassificationRecord(BaseModel):
    """Per-unit sidecar row written by the shadow runner."""

    unit_id: str
    document_key: str | None = None
    document_hash: str | None = None
    batch_id: str
    source_text: str
    assertion_type: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    question_set_version: str
    provider: str
    adapter_version: str
    model_version: str
    results: list[DecisionResult]
    coverage_status: CoverageStatus
    missing_question_ids: list[str] = Field(default_factory=list)
    retry_count: int = 0
    latency_ms: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ShadowClassificationArtifact(BaseModel):
    """Versioned evaluation sidecar; never mutates DocumentAnalysis."""

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    question_set_version: str
    provider: str
    adapter_version: str
    model_version: str
    document_key: str | None = None
    document_hash: str | None = None
    units: list[UnitClassificationRecord]
    batch_results: list[DecisionBatchResult] = Field(default_factory=list)
    incomplete_batch_count: int = 0
    permanent_error_count: int = 0
    total_latency_ms: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
