"""Recent ingest — what's new since last cursor."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from src.claim_notes.models import ClaimNote
from src.claim_notes.products.models import RecentIngestResult


def recent_ingest(
    notes: Iterable[ClaimNote],
    *,
    since: date | datetime,
) -> RecentIngestResult:
    """Return claim notes with ``source_date`` strictly after ``since``."""
    cutoff = since.date() if isinstance(since, datetime) else since
    selected = [
        note
        for note in notes
        if note.source_date is not None and note.source_date > cutoff
    ]
    selected.sort(
        key=lambda n: (n.source_date or date.min, n.note_id),
        reverse=True,
    )
    return RecentIngestResult(
        since=cutoff,
        notes=selected,
        note_ids=[n.note_id for n in selected],
    )
