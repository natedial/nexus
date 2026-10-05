"""Thematic digest — before-the-meeting, split by thread-local stance sides."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from src.claim_notes.models import ClaimNote
from src.claim_notes.products.models import (
    ThematicDigestResult,
    ThematicSide,
    ThematicThread,
)

_UNSPECIFIED = "unspecified"


def thematic_digest(
    notes: Iterable[ClaimNote],
    *,
    thread_key: str | None = None,
) -> ThematicDigestResult:
    """Group notes by claim_key (thread); sides = stance on that thread.

    Side is never a global hawk/dove label and not a fixed publisher bucket.
    """
    by_thread: dict[str, list[ClaimNote]] = defaultdict(list)
    for note in notes:
        key = note.claim_key or f"note:{note.note_id}"
        if thread_key is not None and key != thread_key:
            continue
        by_thread[key].append(note)

    threads: list[ThematicThread] = []
    for key in sorted(by_thread):
        members = by_thread[key]
        by_stance: dict[str, list[ClaimNote]] = defaultdict(list)
        for note in members:
            stance = (note.stance or "").strip() or _UNSPECIFIED
            by_stance[stance].append(note)
        sides = [
            ThematicSide(
                stance=stance,
                notes=by_stance[stance],
                speakers=sorted(
                    {n.speaker for n in by_stance[stance] if n.speaker}
                ),
            )
            for stance in sorted(by_stance)
        ]
        threads.append(
            ThematicThread(thread_key=key, sides=sides, note_count=len(members))
        )
    return ThematicDigestResult(threads=threads)
