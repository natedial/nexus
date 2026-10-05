"""Author evolution — how a speaker's view changed over time."""

from __future__ import annotations

from datetime import date
from typing import Iterable

from src.claim_notes.models import ClaimNote
from src.claim_notes.products.models import (
    AuthorEvolutionEvent,
    AuthorEvolutionResult,
)


def author_evolution(
    notes: Iterable[ClaimNote],
    *,
    speaker: str,
) -> AuthorEvolutionResult:
    """Timeline for one speaker; publisher stays provenance, not identity."""
    target = speaker.strip()
    if not target:
        raise ValueError("speaker is required")

    selected = [n for n in notes if n.speaker.strip() == target]
    selected.sort(
        key=lambda n: (n.source_date or date.min, n.note_id),
    )
    events = [
        AuthorEvolutionEvent(
            source_date=note.source_date,
            note_id=note.note_id,
            claim=note.claim,
            thread_role=note.thread_role,
            publisher=note.publisher,
            cause_edge_count=len(note.cause_edges),
            claim_key=note.claim_key,
        )
        for note in selected
    ]
    return AuthorEvolutionResult(
        speaker=target,
        events=events,
        extend_or_break_count=sum(
            1 for e in events if e.thread_role in {"extend", "break"}
        ),
    )
