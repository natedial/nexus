"""Claim-note contract (claim-note-v1).

Product-facing record for one argument. Separate from analyst ClaimNode /
argument_map extraction; those remain the semantic store. This schema is the
shared input for the five claim-note products.

Cause edges are speaker-asserted only — stored as said, not fact-checked, and
not enforced against any causal world model. Dexter fact-check of an edge is a
later pass.

Dexter live support is a pointer, not an in-Nexus call: the product marks a
pass as awaiting and stops; Dexter runs externally and attaches findings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CLAIM_NOTE_SCHEMA_VERSION = "claim-note-v1"

ThreadRole = Literal["assert", "extend", "break"]
SupportKind = Literal["ingested_document_text", "live_data"]
CausePolarity = Literal["supports", "undermines", "unspecified"]
# Role on the claim note — not a 0–1 significance score.
SpeakerWeight = Literal[
    "chair",
    "voter",
    "non-voter",
    "interview",
    "research_author",
]
# Pointer lifecycle: product marks awaiting and stops; completed = external attach.
DexterPassStatus = Literal["awaiting", "completed", "failed"]


class TimeWindow(BaseModel):
    """Time window the claim covers (not when it was ingested)."""

    start: date | None = None
    end: date | None = None
    label: str | None = None  # e.g. "Q2 2026", "H2", "next 12m"

    @model_validator(mode="after")
    def _require_anchor(self) -> TimeWindow:
        if self.start is None and self.end is None and not (self.label or "").strip():
            raise ValueError("time_window needs start, end, and/or label")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("time_window.start must be on or before end")
        return self


class CauseEdge(BaseModel):
    """Speaker-asserted causal link on the claim note.

    Own edge, separate from thread_role. Unchecked — not a fact-check and not
    a world-model edge. Kept so a later Dexter/model pass needs no reparse.
    """

    cause: str
    effect: str
    polarity: CausePolarity = "unspecified"
    as_stated: str | None = None

    @field_validator("cause", "effect")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("cause and effect must be non-empty")
        return text


class DexterSource(BaseModel):
    """Sourced + dated reference attached by external Dexter."""

    name: str
    url: str | None = None
    published_at: date | None = None
    retrieved_at: date

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Dexter source name must be non-empty")
        return text


class DexterFinding(BaseModel):
    """One live figure attached by external Dexter. Products never invent these."""

    label: str
    value: str
    unit: str | None = None
    as_of: date
    source_index: int = Field(..., ge=0)


class DexterResearchPass(BaseModel):
    """Pointer to an external Dexter research pass for live_data support.

    Nexus does not call Dexter. The product creates an ``awaiting`` pointer and
    stops. Dexter runs externally and attaches ``completed`` findings with
    as-of times and sources. Products must not invent or fill numbers.
    """

    pass_id: str
    requested_at: datetime
    query: str
    status: DexterPassStatus = "awaiting"
    completed_at: datetime | None = None
    sources: list[DexterSource] = Field(default_factory=list)
    findings: list[DexterFinding] = Field(default_factory=list)

    @field_validator("pass_id", "query")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("pass_id and query must be non-empty")
        return text

    @model_validator(mode="after")
    def _status_rules(self) -> DexterResearchPass:
        for finding in self.findings:
            if finding.source_index >= len(self.sources):
                raise ValueError(
                    f"finding source_index {finding.source_index} out of range "
                    f"for {len(self.sources)} sources"
                )
        if self.status in ("awaiting", "failed"):
            if self.findings:
                raise ValueError(
                    f"dexter_pass status={self.status!r} must not carry findings; "
                    "products never fill numbers — Dexter attaches them externally"
                )
            if self.sources:
                raise ValueError(
                    f"dexter_pass status={self.status!r} must not carry sources "
                    "until Dexter attaches a completed result"
                )
        if self.status == "completed":
            if not self.sources:
                raise ValueError("completed Dexter pass requires sources")
            if not self.findings:
                raise ValueError("completed Dexter pass requires findings")
            if self.completed_at is None:
                raise ValueError("completed Dexter pass requires completed_at")
        return self


class ClaimNote(BaseModel):
    """One claim-note record per argument (claim-note-v1)."""

    schema_version: str = CLAIM_NOTE_SCHEMA_VERSION
    note_id: str
    claim: str
    speaker: str  # who said it
    thread_role: ThreadRole
    time_window: TimeWindow
    support_kind: SupportKind
    speaker_weight: SpeakerWeight
    cause_edges: list[CauseEdge] = Field(default_factory=list)
    publisher: str | None = None  # which document/house it came from — distinct from speaker
    thread_target_note_id: str | None = None
    claim_key: str | None = None
    research_id: int | None = None
    document_key: str | None = None
    source_date: date | None = None
    rationale: str = ""
    conditions: list[str] = Field(default_factory=list)
    # Thread-local stance for thematic side grouping — not a global hawk/dove label.
    stance: str | None = None
    dexter_pass: DexterResearchPass | None = None

    @field_validator("note_id", "claim", "speaker")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("note_id, claim, and speaker must be non-empty")
        return text

    @model_validator(mode="after")
    def _cross_field_rules(self) -> ClaimNote:
        if self.schema_version != CLAIM_NOTE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {CLAIM_NOTE_SCHEMA_VERSION!r}"
            )
        if self.thread_role in ("extend", "break") and not self.thread_target_note_id:
            raise ValueError(
                f"thread_role={self.thread_role!r} requires thread_target_note_id"
            )
        if self.support_kind == "live_data":
            if self.dexter_pass is None:
                raise ValueError("live_data support_kind requires dexter_pass")
        elif self.dexter_pass is not None:
            raise ValueError(
                "dexter_pass is only allowed when support_kind is live_data"
            )
        return self
