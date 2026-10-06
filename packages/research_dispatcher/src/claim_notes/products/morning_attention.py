"""Morning attention — own 3–5 point surface.

Claim source (locked 2026-10-06): claim notes projected from analyst
``argument_map`` / ClaimNodes. Optional G10 calendar fill. LIBRARY titles are
**not** a second claims extractor — they do not pad the surface.

Delivery: own reMarkable notebook (`Morning Attention YYYY-MM-DD`, next to
G10 / Research From) + one-line Grok Bot ping to Nate's 1:1 with Proey
(Proey connectors, same as 5:55/6:10). Empty day = silent.
Does NOT fold into G10 Calendar / Research From; does NOT change 5:55/6:10.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from src.claim_notes.library import (
    LIBRARY_NOTION_URL,
    LIBRARY_RESOURCE_TYPE_FILTER,
    LibraryDigestInput,
    LibraryDigestReader,
    LibraryResearchNote,
)
from src.claim_notes.models import ClaimNote
from src.claim_notes.products.models import (
    MorningAttentionDelivery,
    MorningAttentionPoint,
    MorningAttentionSurface,
)


def build_morning_attention(
    notes: Iterable[ClaimNote],
    *,
    calendar_events: Sequence[Mapping[str, Any]] | None = None,
    library: LibraryDigestInput | LibraryDigestReader | Sequence[LibraryResearchNote] | None = None,
    max_points: int = 5,
) -> MorningAttentionSurface:
    """Build the morning-attention own surface (3–5 points)."""
    if max_points < 3 or max_points > 5:
        raise ValueError("morning attention must target 3–5 points")

    library_input = _coerce_library(library)
    events = list(calendar_events or [])
    points: list[MorningAttentionPoint] = []

    # Prefer high-weight claim notes (argument_map projection), then calendar.
    ranked_notes = sorted(
        list(notes),
        key=lambda n: (_weight_rank(n.speaker_weight), n.source_date or "", n.note_id),
        reverse=True,
    )
    for note in ranked_notes:
        if len(points) >= max_points:
            break
        points.append(
            MorningAttentionPoint(
                rank=len(points) + 1,
                text=f"{note.speaker}: {note.claim}",
                note_id=note.note_id,
                source="claim_note",
            )
        )

    for event in events:
        if len(points) >= max_points:
            break
        label = _event_label(event)
        if not label:
            continue
        points.append(
            MorningAttentionPoint(
                rank=len(points) + 1,
                text=label,
                source="calendar",
            )
        )

    # Never invent content to pad to 3. Never pad from LIBRARY body/title
    # (demoted — argument_map is the only claim source). Delivery flags stay
    # hard-locked off for tablet fold-ins and 5:55 / 6:10 schedule changes.
    return MorningAttentionSurface(
        points=points[:max_points],
        delivery=MorningAttentionDelivery(),
        calendar_event_count=len(events),
        library_note_count=len(library_input.notes),
    )


def _coerce_library(
    library: LibraryDigestInput | LibraryDigestReader | Sequence[LibraryResearchNote] | None,
) -> LibraryDigestInput:
    if library is None:
        return LibraryDigestInput()
    if isinstance(library, LibraryDigestInput):
        if library.resource_type_filter != LIBRARY_RESOURCE_TYPE_FILTER:
            raise ValueError(
                "LIBRARY input must use Resource Type = Research Note only"
            )
        return library
    if hasattr(library, "list_research_notes"):
        notes = library.list_research_notes()  # type: ignore[union-attr]
        return LibraryDigestInput(
            resource_type_filter=LIBRARY_RESOURCE_TYPE_FILTER,
            notion_url=LIBRARY_NOTION_URL,
            notes=list(notes),
        )
    return LibraryDigestInput(notes=list(library))  # type: ignore[arg-type]


def _weight_rank(role: str) -> int:
    order = {
        "chair": 5,
        "voter": 4,
        "interview": 3,
        "research_author": 2,
        "non-voter": 1,
    }
    return order.get(role, 0)


def _event_label(event: Mapping[str, Any]) -> str:
    name = str(event.get("event_name") or event.get("description") or "").strip()
    when = str(event.get("event_date") or event.get("date") or "").strip()
    country = str(event.get("country") or "").strip()
    if not name:
        return ""
    parts = [p for p in (when, country, name) if p]
    return " · ".join(parts)
