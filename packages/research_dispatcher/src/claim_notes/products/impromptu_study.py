"""Impromptu study — on-demand topic query over claim notes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from src.claim_notes.models import ClaimNote, DexterResearchPass
from src.claim_notes.products.models import ImpromptuStudyHit, ImpromptuStudyResult
from src.claim_notes.validate import live_findings_allowed


def impromptu_study(
    notes: Iterable[ClaimNote],
    *,
    query: str,
    need_live_numbers: bool = False,
) -> ImpromptuStudyResult:
    """Match notes by claim_key / claim / rationale text.

    When ``need_live_numbers`` is true, attach an ``awaiting`` Dexter pointer
    and stop — never invent or fill numbers inside Nexus.
    """
    q = query.strip().lower()
    if not q:
        raise ValueError("query is required")

    hits: list[ImpromptuStudyHit] = []
    for note in notes:
        reason = _match_reason(note, q)
        if reason:
            hits.append(ImpromptuStudyHit(note=note, match_reason=reason))

    pointers: list[DexterResearchPass] = []
    if need_live_numbers:
        pointers.append(
            DexterResearchPass(
                pass_id=f"dex-impromptu-{uuid4().hex[:10]}",
                requested_at=datetime.now(timezone.utc),
                query=query.strip(),
                status="awaiting",
            )
        )

    # Fail closed: never report invented live figures from this product.
    for hit in hits:
        if hit.note.support_kind == "live_data" and not live_findings_allowed(hit.note):
            # Hits remain; callers must gate figures via live_findings_allowed.
            pass

    return ImpromptuStudyResult(
        query=query.strip(),
        hits=hits,
        dexter_pointers=pointers,
        live_numbers_invented=False,
    )


def _match_reason(note: ClaimNote, q: str) -> str | None:
    if note.claim_key and q in note.claim_key.lower():
        return "claim_key"
    if q in note.claim.lower():
        return "claim"
    if note.rationale and q in note.rationale.lower():
        return "rationale"
    if note.stance and q in note.stance.lower():
        return "stance"
    return None
