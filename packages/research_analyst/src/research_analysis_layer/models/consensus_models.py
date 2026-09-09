"""Cross-author consensus and divergence points (Slice 2 Task 4).

A position/side is always a publisher. These models match
`prompts/agents/_components/consensus_schema.md`. They are computed from
resolved argument maps, not emitted by the synthesizer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GroundedReason(BaseModel):
    """One grounded reason attached to a consensus or divergence point."""

    text: str
    ref_type: Literal["assertion", "evidence", "chunk", "theme", "corpus"] = "evidence"
    ref_key: str


class ConsensusPoint(BaseModel):
    """Where distinct publishers agree on the same-direction claim."""

    point: str
    positions: list[str] = Field(..., min_length=2)
    reasons: list[GroundedReason] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0, le=1)
    subject: str
    predicate: str
    polarity: str
    horizon_bucket: str
    source_diversity: int
    contradiction_count: int = 0


class DivergenceSide(BaseModel):
    """One publisher's side of a split."""

    position: str
    claim: str
    polarity: str
    reasons: list[GroundedReason] = Field(default_factory=list)


class DivergencePoint(BaseModel):
    """Where distinct publishers take opposing polarity on the same cluster."""

    point: str
    sides: list[DivergenceSide] = Field(..., min_length=2)
    verdict: Literal["position_favored", "contested", "needs_more_evidence"] = "contested"
    favored_position: str | None = None
    verdict_reason: str = "opposing publisher polarities; no favored side"
    materiality: Literal["high", "medium", "low"] = "medium"
    subject: str
    predicate: str
    horizon_bucket: str
    source_diversity: int
    contradiction_count: int = 1


class ConsensusSnapshot(BaseModel):
    """Agreements and disagreements for a corpus window."""

    agreements: list[ConsensusPoint] = Field(default_factory=list)
    disagreements: list[DivergencePoint] = Field(default_factory=list)
    min_publishers: int = 2
    clustered_claim_count: int = 0
    skipped_unresolved_count: int = 0
