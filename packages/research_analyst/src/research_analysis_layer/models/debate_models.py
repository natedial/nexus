"""Pydantic models for the debate forum layer.

This module defines the core debate artifacts used in the document-local debate forum.
Debate state is separate from world state - debate artifacts are temporary reasoning
state tied to a document/run, not durable analyst memory.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DebateRelationType(str, Enum):
    """Types of relations between debate arguments."""

    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    REBUTS = "rebuts"
    CONCEDES = "concedes"
    DUPLICATES = "duplicates"
    SYNTHESIZES = "synthesizes"


class DebateVerdictLabel(str, Enum):
    """Verdict labels for adjudicated arguments."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CONTESTED = "contested"
    SYNTHESIZED = "synthesized"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class RebuttalStance(str, Enum):
    """Stance options for rebuttal agents."""

    DEFEND = "defend"
    NARROW = "narrow"
    CONCEDE = "concede"


class ChallengeMode(str, Enum):
    """Challenge modes for challenger agents."""

    REJECT = "reject"
    WEAKEN = "weaken"
    CONTRADICT = "contradict"


class ThesisType(str, Enum):
    """Types of thesis/positioning arguments."""

    THESIS = "thesis"
    CONTRARIAN = "contrarian"
    POSITIONING = "positioning"


class ArgumentMetadata(BaseModel):
    """Metadata for a debate argument."""

    prompt_version: str = ""
    model_used: str = ""
    attempt_count: int = 1


class StableEvidenceKey(BaseModel):
    """Stable local keys for referencing deterministic substrate.

    These keys are derived from local coordinates and are available before
    persistence. Format: {type}:{parent}-{index}, e.g., 'assertion:chunk-3:assertion-2'
    """

    chunk_key: str | None = Field(
        None,
        description="Stable key for the chunk this evidence/assertion comes from, e.g., 'chunk-3'",
    )
    evidence_key: str | None = Field(
        None,
        description="Stable key for the evidence unit, e.g., 'chunk-3:evidence-1'",
    )
    assertion_key: str | None = Field(
        None,
        description="Stable key for the assertion, e.g., 'chunk-3:assertion-2'",
    )
    theme_key: str | None = Field(
        None,
        description="Optional stable key for the parser theme, e.g., 'theme-5'",
    )

    @classmethod
    def from_chunk_order(cls, chunk_order: int) -> "StableEvidenceKey":
        """Create a chunk key from chunk order."""
        return cls(chunk_key=f"chunk-{chunk_order}")

    @classmethod
    def from_assertion(
        cls, chunk_order: int, assertion_order: int
    ) -> "StableEvidenceKey":
        """Create assertion keys from orders."""
        chunk_key = f"chunk-{chunk_order}"
        assertion_key = f"chunk-{chunk_order}:assertion-{assertion_order}"
        return cls(chunk_key=chunk_key, assertion_key=assertion_key)

    @classmethod
    def from_evidence(
        cls, chunk_order: int, evidence_order: int
    ) -> "StableEvidenceKey":
        """Create evidence keys from orders."""
        chunk_key = f"chunk-{chunk_order}"
        evidence_key = f"chunk-{chunk_order}:evidence-{evidence_order}"
        return cls(chunk_key=chunk_key, evidence_key=evidence_key)


class DebateArgument(BaseModel):
    """A single argument in the debate forum.

    Arguments must be anchored to deterministic evidence. Every argument
    should reference stable local keys for the substrate it uses.
    """

    argument_id: str = Field(..., description="Unique identifier for this argument")
    session_id: str = Field(..., description="Parent debate session ID")
    turn_name: str = Field(..., description="Name of the turn this argument came from")
    agent_name: str = Field(..., description="Agent that produced this argument")

    thesis_type: ThesisType = Field(
        default=ThesisType.THESIS,
        description="Type of thesis/positioning this argument represents",
    )

    argument_text: str = Field(..., description="The main text of the argument")

    target_claim_id: str | None = Field(
        None,
        description="ID of the argument this is targeting (for challenges/rebuttals)",
    )

    cited_chunk_keys: list[str] = Field(
        default_factory=list,
        description="List of chunk keys this argument references",
    )
    cited_evidence_keys: list[str] = Field(
        default_factory=list,
        description="List of evidence keys this argument references",
    )
    cited_assertion_keys: list[str] = Field(
        default_factory=list,
        description="List of assertion keys this argument references",
    )

    uncertainty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Uncertainty level of the argument (0=confident, 1=uncertain)",
    )
    qualifier_text: str | None = Field(
        None,
        description="Qualifying conditions or caveats for this argument",
    )

    target_instrument: str | None = Field(
        None,
        description="Target instrument if applicable, e.g., 'EUR/USD', '10Y Treasury'",
    )
    time_horizon: str | None = Field(
        None,
        description="Time horizon, e.g., 'weeks', 'months', 'quarters'",
    )
    invalidation_condition: str | None = Field(
        None,
        description="Condition that would invalidate this argument",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: ArgumentMetadata = Field(default_factory=ArgumentMetadata)


class DebateRelation(BaseModel):
    """A relation between two debate arguments."""

    relation_id: str = Field(..., description="Unique identifier for this relation")
    session_id: str = Field(..., description="Parent debate session ID")

    relation_type: DebateRelationType = Field(..., description="Type of relation")

    source_argument_id: str = Field(
        ..., description="ID of the argument providing the relation"
    )
    target_argument_id: str = Field(
        ..., description="ID of the argument being related to"
    )

    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Strength of the relation (0=weak, 1=strong)",
    )

    explanation: str | None = Field(
        None,
        description="Optional explanation for why this relation exists",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeterministicScoreFeature(BaseModel):
    """Deterministic feature scores for an argument.

    These are computed from the argument's structure and references,
    before LLM adjudication.
    """

    evidence_count: int = Field(
        default=0,
        ge=0,
        description="Number of evidence/assertion references",
    )
    evidence_diversity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Diversity of evidence sources (0=monosource, 1=diverse)",
    )
    assertion_alignment: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Alignment with deterministic assertions (0=mismatch, 1=aligned)",
    )
    has_contradiction: bool = Field(
        default=False,
        description="Whether argument contradicts deterministic substrate",
    )
    has_accepted_contradiction: bool = Field(
        default=False,
        description="Whether argument contradicts already-accepted arguments",
    )
    time_horizon_specificity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Specificity of time horizon (0=vague, 1=specific)",
    )
    conditional_clarity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Clarity of conditions/invalidation (0=unclear, 1=clear)",
    )
    is_novel: bool = Field(
        default=True,
        description="Whether argument is novel vs duplicate restatement",
    )
    is_actionable: bool = Field(
        default=False,
        description="Whether argument has actionable trading implications",
    )


class DebateScore(BaseModel):
    """Scoring for a debate argument combining deterministic and LLM-judge signals."""

    score_id: str = Field(..., description="Unique identifier for this score")
    session_id: str = Field(..., description="Parent debate session ID")
    argument_id: str = Field(..., description="ID of the argument being scored")

    deterministic_features: DeterministicScoreFeature = Field(
        default_factory=DeterministicScoreFeature
    )

    pairwise_wins: int = Field(
        default=0,
        ge=0,
        description="Number of pairwise comparisons won",
    )
    pairwise_losses: int = Field(
        default=0,
        ge=0,
        description="Number of pairwise comparisons lost",
    )
    pairwise_ties: int = Field(
        default=0,
        ge=0,
        description="Number of pairwise comparisons tied",
    )

    llm_judge_score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="LLM judge score if available",
    )

    final_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Combined final score",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DebateVerdict(BaseModel):
    """Verdict for an adjudicated argument."""

    verdict_id: str = Field(..., description="Unique identifier for this verdict")
    session_id: str = Field(..., description="Parent debate session ID")
    argument_id: str = Field(..., description="ID of the argument being adjudicated")

    verdict_label: DebateVerdictLabel = Field(..., description="The verdict label")

    reason: str = Field(
        default="",
        description="Brief explanation for the verdict",
    )

    synthesizes_from: list[str] = Field(
        default_factory=list,
        description="Argument IDs that were synthesized into this verdict (for synthesized verdicts)",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DebateTurn(BaseModel):
    """A single turn in the debate forum."""

    turn_id: str = Field(..., description="Unique identifier for this turn")
    session_id: str = Field(..., description="Parent debate session ID")

    turn_name: Literal["proposal", "challenge", "rebuttal", "adjudication", "synthesis"]
    turn_order: int = Field(..., description="Order of this turn in the session")

    agent_name: str = Field(..., description="Agent that executed this turn")

    target_argument_ids: list[str] = Field(
        default_factory=list,
        description="Argument IDs targeted in this turn (for challenge/rebuttal)",
    )

    turn_summary: str = Field(
        default="",
        description="Summary of what happened in this turn",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DebateSession(BaseModel):
    """A complete debate session for a single document analysis.

    A session is anchored to (research_id, document_hash, analysis_version, run_id)
    and contains all turns, arguments, relations, scores, and verdicts.
    """

    session_id: str = Field(..., description="Unique identifier for this session")
    research_id: int = Field(..., description="Research ID this session belongs to")
    document_hash: str = Field(..., description="Document hash this session analyzes")
    analysis_version: str = Field(..., description="Analysis version")
    run_id: int = Field(..., description="Run ID that created this session")

    status: Literal["active", "completed", "superseded", "abandoned"] = Field(
        default="active",
        description="Current status of the session",
    )

    turns: list[DebateTurn] = Field(default_factory=list)
    arguments: list[DebateArgument] = Field(default_factory=list)
    relations: list[DebateRelation] = Field(default_factory=list)
    scores: list[DebateScore] = Field(default_factory=list)
    verdicts: list[DebateVerdict] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ForumContext(BaseModel):
    """Payload shape for round inputs in debate mode.

    This is the structured input fed to debate-capable agents,
    containing the question set, arguments, relations, and open targets.
    """

    research_id: int
    document_hash: str
    analysis_version: str
    run_id: int

    question_set: list[str] = Field(
        default_factory=list,
        description="Questions the debate is addressing",
    )

    arguments: list[DebateArgument] = Field(
        default_factory=list,
        description="All arguments in the session so far",
    )
    relations: list[DebateRelation] = Field(
        default_factory=list,
        description="All relations between arguments",
    )
    scores: list[DebateScore] = Field(
        default_factory=list,
        description="Available score bundles for the surfaced arguments",
    )
    verdicts: list[DebateVerdict] = Field(
        default_factory=list,
        description="Available verdicts for the surfaced arguments",
    )

    open_targets: list[str] = Field(
        default_factory=list,
        description="Argument IDs that need attention (challenge/rebuttal targets)",
    )

    budget: dict[str, int] = Field(
        default_factory=dict,
        description="Budget info: {remaining_tool_calls, remaining_rounds, etc.}",
    )

    world_context: dict[str, Any] | None = Field(
        default=None,
        description="Optional world model context for cross-reference",
    )


class DebateRoundOutput(BaseModel):
    """Output from a debate round execution."""

    turn: DebateTurn
    arguments: list[DebateArgument] = Field(default_factory=list)
    relations: list[DebateRelation] = Field(default_factory=list)
    scores: list[DebateScore] = Field(default_factory=list)
    verdicts: list[DebateVerdict] = Field(default_factory=list)

    error: str | None = Field(
        default=None,
        description="Error message if the round failed",
    )
