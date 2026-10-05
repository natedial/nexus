"""Result models for the five claim-note product surfaces."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.claim_notes.models import ClaimNote, DexterResearchPass

DeliveryChannel = Literal["remarkable_notebook", "chat_ping"]


class RecentIngestResult(BaseModel):
    since: date
    notes: list[ClaimNote] = Field(default_factory=list)
    note_ids: list[str] = Field(default_factory=list)


class ThematicSide(BaseModel):
    """One side of a thread — stance on *that thread*, not a global label."""

    stance: str
    notes: list[ClaimNote] = Field(default_factory=list)
    speakers: list[str] = Field(default_factory=list)


class ThematicThread(BaseModel):
    thread_key: str
    sides: list[ThematicSide] = Field(default_factory=list)
    note_count: int = 0


class ThematicDigestResult(BaseModel):
    threads: list[ThematicThread] = Field(default_factory=list)


class MorningAttentionPoint(BaseModel):
    rank: int
    text: str
    note_id: str | None = None
    source: Literal["claim_note", "calendar", "library"] = "claim_note"


class MorningAttentionDelivery(BaseModel):
    """Own surface delivery — never folded into G10 Calendar / Research From.

    Chat ping is Grok Bot (same as 5:55/6:10), never SMTP email.
    Empty day = silent (no notebook, no ping).
    """

    remarkable_notebook: bool = True
    grok_bot_chat_ping: bool = True
    chat_ping: bool = True  # alias — always Grok Bot, never SMTP
    fold_into_g10_calendar: bool = False
    fold_into_research_from: bool = False
    alter_tablet_555: bool = False
    alter_tablet_610: bool = False
    pattern: str = "own_remarkable_notebook_plus_grok_bot_ping"
    empty_day_silent: bool = True


class MorningAttentionSurface(BaseModel):
    points: list[MorningAttentionPoint] = Field(default_factory=list)
    delivery: MorningAttentionDelivery = Field(
        default_factory=MorningAttentionDelivery
    )
    calendar_event_count: int = 0
    library_note_count: int = 0


class AuthorEvolutionEvent(BaseModel):
    source_date: date | None = None
    note_id: str
    claim: str
    thread_role: str
    publisher: str | None = None
    cause_edge_count: int = 0
    claim_key: str | None = None


class AuthorEvolutionResult(BaseModel):
    speaker: str
    events: list[AuthorEvolutionEvent] = Field(default_factory=list)
    extend_or_break_count: int = 0


class ImpromptuStudyHit(BaseModel):
    note: ClaimNote
    match_reason: str


class ImpromptuStudyResult(BaseModel):
    query: str
    hits: list[ImpromptuStudyHit] = Field(default_factory=list)
    dexter_pointers: list[DexterResearchPass] = Field(default_factory=list)
    live_numbers_invented: bool = False
