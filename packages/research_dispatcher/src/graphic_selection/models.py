"""Provider-neutral decision-model contracts for graphic selection.

Mirrors the research_analyst DecisionModel shape (Choice + Nouls, batches,
shadow artifacts) with a graphic-selection task set — not statement_type.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QuestionKind = Literal["choice", "noul"]
DecisionStatus = Literal["complete", "uncertain", "failed", "none"]
BatchStatus = Literal["complete", "partial", "failed"]
CoverageStatus = Literal["full", "partial", "missing", "failed"]

ARTIFACT_SCHEMA_VERSION = "graphic-selection-artifact-v1"
DECISION_RECORD_SCHEMA = "graphic-selection-v1"
QUESTION_SET_VERSION = "graphic-question-set-v1"


class DecisionModelMetadata(BaseModel):
    provider_name: str
    model_version: str
    question_set_version: str
    adapter_version: str


class FrozenQuestionSpec(BaseModel):
    question_id: str
    question_kind: QuestionKind
    wording: str
    options: list[str] | None = None
    noul_criteria: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate(self) -> FrozenQuestionSpec:
        if self.question_kind == "choice":
            if not self.options:
                raise ValueError("choice questions require options")
            if self.noul_criteria:
                raise ValueError("choice questions must not supply noul_criteria")
        elif self.options:
            raise ValueError("noul questions must not supply options")
        return self


class QuestionSetSnapshot(BaseModel):
    version: str
    content_hash: str
    questions: list[FrozenQuestionSpec]


class DecisionQuestion(BaseModel):
    question_id: str
    target_unit_id: str
    question_kind: QuestionKind
    wording: str
    question_set_version: str = QUESTION_SET_VERSION
    options: list[str] | None = None
    noul_criteria: dict[str, str] | None = None

    @model_validator(mode="after")
    def _validate(self) -> DecisionQuestion:
        if self.question_kind == "choice":
            if not self.options:
                raise ValueError("choice questions require options")
        elif self.options:
            raise ValueError("noul questions must not supply options")
        return self


class DecisionUnit(BaseModel):
    """One concept block prepared for graphic selection."""

    unit_id: str
    text: str = ""
    data_shape: str = "none"
    available_fields: list[str] = Field(default_factory=list)
    # Shape-derived eligibility hints (deterministic); never significance.
    eligibility: dict[str, bool] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class DecisionBatch(BaseModel):
    batch_id: str
    shared_context: str = (
        "Graphic selection is shape→pattern only. Ignore importance, "
        "speaker weight, and whether a claim deserves a chart."
    )
    units: list[DecisionUnit]
    questions: list[DecisionQuestion]
    document_key: str | None = None
    document_hash: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerDistribution(BaseModel):
    probabilities: dict[str, float]
    selected: str | None = None
    raw_probability: float | None = None
    calibrated_probability: float | None = None

    @field_validator("probabilities")
    @classmethod
    def _validate_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("probabilities must not be empty")
        total = sum(float(v) for v in value.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"probabilities must sum to 1.0, got {total}")
        return {str(k): float(v) for k, v in value.items()}


class DecisionResult(BaseModel):
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


class DecisionBatchResult(BaseModel):
    batch_id: str
    status: BatchStatus
    results: list[DecisionResult]
    metadata: DecisionModelMetadata
    missing_question_ids: list[str] = Field(default_factory=list)
    unknown_question_ids: list[str] = Field(default_factory=list)
    retry_count: int = 0
    latency_ms: float | None = None
    provider_error: str | None = None


class ConceptBlock(BaseModel):
    """Agent/pipeline input for one explanatory concept (shape only)."""

    concept_id: str
    concept_text: str = ""
    data_shape: str = "none"
    available_fields: list[str] = Field(default_factory=list)
    expected_pattern_id: str | None = None  # fixtures only
    notes: str | None = None


class GraphicDecisionRecord(BaseModel):
    """Agent-consumable chooser output."""

    schema_version: str = DECISION_RECORD_SCHEMA
    question_set_version: str = QUESTION_SET_VERSION
    concept_id: str
    choice: dict[str, Any]
    nouls: dict[str, bool]
    emit: dict[str, Any]
    rationale_short: str = ""
    provider: str | None = None
    model_version: str | None = None
    adapter_version: str | None = None


class UnitGraphicRecord(BaseModel):
    unit_id: str
    data_shape: str
    available_fields: list[str] = Field(default_factory=list)
    decision: GraphicDecisionRecord
    results: list[DecisionResult] = Field(default_factory=list)
    coverage_status: CoverageStatus = "full"


class GraphicSelectionArtifact(BaseModel):
    """Shadow-ready sidecar for a fixture or dry-run."""

    schema_version: str = ARTIFACT_SCHEMA_VERSION
    question_set_version: str = QUESTION_SET_VERSION
    question_set: QuestionSetSnapshot | None = None
    provider: str
    adapter_version: str
    model_version: str
    document_key: str | None = None
    units: list[UnitGraphicRecord] = Field(default_factory=list)
    batch_results: list[DecisionBatchResult] = Field(default_factory=list)
