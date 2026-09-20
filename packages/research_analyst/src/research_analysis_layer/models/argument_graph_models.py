"""Argument-graph query results (Slice 2 Task 5).

Hits are joins over Author (publisher) → Claim → Evidence (referent_key).
A position is always a publisher. Every row carries provenance + rationale.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GraphSide(BaseModel):
    """One publisher's claim on a graph hit."""

    publisher: str
    research_id: int | None = None
    claim: str
    claim_key: str
    polarity: str
    rationale: str
    support_strength: str
    evidence_text: str = ""
    referent_keys: list[str] = Field(default_factory=list)


class InterpretationGap(BaseModel):
    """Same referent_key, opposing-polarity claims, distinct publishers."""

    referent_key: str
    family: str
    source_diversity: int
    sides: list[GraphSide] = Field(..., min_length=2)
    rationale: str


class EvidenceIndependence(BaseModel):
    """Same claim_key: disjoint referents (robust) vs shared (herding)."""

    claim_key: str
    kind: Literal["robust", "herding", "mixed"]
    source_diversity: int
    positions: list[str] = Field(..., min_length=2)
    shared_referents: list[str] = Field(default_factory=list)
    referents_by_publisher: dict[str, list[str]] = Field(default_factory=dict)
    rationale: str


class EvidenceContradiction(BaseModel):
    """A claim standing against a referent linked to the opposing polarity."""

    claim_key: str
    publisher: str
    research_id: int | None = None
    claim: str
    polarity: str
    referent_key: str
    opposing_sides: list[GraphSide] = Field(..., min_length=1)
    rationale: str


class BackedVsAsserted(BaseModel):
    """Same claim_key evidenced at one house and asserted at another."""

    claim_key: str
    source_diversity: int
    evidenced: list[str] = Field(default_factory=list)
    asserted: list[str] = Field(default_factory=list)
    reasoned: list[str] = Field(default_factory=list)
    rationale: str


class ArgumentGraphSnapshot(BaseModel):
    """All four argument-graph query results for a corpus window."""

    interpretation_gaps: list[InterpretationGap] = Field(default_factory=list)
    independence: list[EvidenceIndependence] = Field(default_factory=list)
    contradictions: list[EvidenceContradiction] = Field(default_factory=list)
    backed_vs_asserted: list[BackedVsAsserted] = Field(default_factory=list)
    min_publishers: int = 2
    clustered_claim_count: int = 0
    skipped_unresolved_count: int = 0
