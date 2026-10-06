"""Demoted: LIBRARY Research Note → ClaimNote (not the live 6:25 feed).

Locked 2026-10-06: Morning Attention claims come from analyst ``argument_map``
ClaimNodes via ``project.py``. Do **not** wire this module into the live Proey
path. Kept for offline/legacy tests only — supersedes draft PR #51 body extract.

Rules (when used offline):
- Copy title/summary **as stated** — never invent numbers or Dexter findings.
- ``support_kind=ingested_document_text`` (LIBRARY text, not live_data).
- ``speaker`` vs ``publisher`` stay distinct (desk vs Notion LIBRARY house).
- Empty cause_edges — do not invent speaker-asserted causal links.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import date, datetime

from src.claim_notes.library import LibraryResearchNote
from src.claim_notes.models import ClaimNote, TimeWindow
from src.claim_notes.validate import validate_claim_note

# Provenance markers — not a person; LIBRARY rows often lack author metadata.
LIBRARY_SPEAKER = "LIBRARY desk"
LIBRARY_PUBLISHER = "Notion LIBRARY"


def project_library_research_note(note: LibraryResearchNote) -> ClaimNote | None:
    """Project one Research Note row. Returns None when there is no usable text."""
    claim = (note.summary or "").strip() or (note.title or "").strip()
    if not claim:
        return None
    source_date = note.source_date
    if source_date is None and note.saved_at is not None:
        stamp = note.saved_at
        source_date = stamp.date() if isinstance(stamp, datetime) else None
    return validate_claim_note(
        ClaimNote(
            note_id=_library_note_id(note, claim),
            claim=claim,
            speaker=LIBRARY_SPEAKER,
            publisher=LIBRARY_PUBLISHER,
            thread_role="assert",
            time_window=_library_time_window(source_date),
            support_kind="ingested_document_text",
            speaker_weight="research_author",
            cause_edges=[],
            document_key=note.url,
            source_date=source_date,
            rationale=(note.title or "").strip(),
        )
    )


def project_library_research_notes(
    notes: Sequence[LibraryResearchNote],
) -> list[ClaimNote]:
    """Project many LIBRARY Research Notes; skips rows with no title/summary."""
    out: list[ClaimNote] = []
    for note in notes:
        projected = project_library_research_note(note)
        if projected is not None:
            out.append(projected)
    return out


def _library_note_id(note: LibraryResearchNote, claim: str) -> str:
    raw = (note.note_id or "").strip()
    if raw:
        return raw
    digest = hashlib.sha1(claim.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", (note.title or "note").strip())
    slug = slug.strip("-")[:40] or "note"
    return f"lib-{slug}-{digest}"


def _library_time_window(source_date: date | None) -> TimeWindow:
    if source_date is not None:
        return TimeWindow(
            start=source_date, end=source_date, label=source_date.isoformat()
        )
    return TimeWindow(label="LIBRARY Research Note")
