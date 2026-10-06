"""LIBRARY digest read path (Proey lock).

Canonical source: Notion LIBRARY database
Filter: Resource Type = Research Note only (same as existing 6:10 digest)
Window: every Research Note saved **since the last run** (not last-night-only).
Link: https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9

Nexus products read through this protocol. Do not invent alternate channels.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field

LIBRARY_NOTION_URL = "https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9"
LIBRARY_RESOURCE_TYPE_FILTER = "Research Note"
# Notion page/DB id from the canonical link (dashed UUID form).
LIBRARY_NOTION_DATABASE_ID = "2839852e-ebb4-806c-9127-c229dcc2ddb9"
LIBRARY_RESOURCE_TYPE_PROPERTY = "Resource Type"


class LibraryResearchNote(BaseModel):
    """One LIBRARY row after the Research Note filter.

    Proey's live ``--library-json`` must include the full page ``body`` for
    Gerhard claim extraction (title/summary alone are not enough).
    """

    title: str = ""
    note_id: str | None = None
    source_date: date | None = None
    saved_at: datetime | None = None  # Notion last_edited / created — since-last-run window
    summary: str = ""
    body: str = ""  # full page body — required for multi-claim extraction
    url: str | None = None
    # Attributed desk/author on the Research Note (JPM, Barclays, …) — never LIBRARY desk.
    speaker: str | None = None
    author: str | None = None  # alias for speaker
    # Source house when the note has one; otherwise extractor defaults to Notion LIBRARY.
    publisher: str | None = None


class LibraryDigestReader(Protocol):
    """Read path for LIBRARY digest inputs."""

    def list_research_notes(
        self, *, since: datetime | None = None
    ) -> list[LibraryResearchNote]:
        """Return Research Note rows saved since ``since`` (inclusive lower bound).

        When ``since`` is None, return all Research Note rows the reader can see.
        Always apply Resource Type = Research Note only.
        """
        ...


class FakeLibraryDigestReader:
    """Fixture-friendly LIBRARY reader — already filtered to Research Note."""

    def __init__(self, notes: list[LibraryResearchNote] | None = None) -> None:
        self._notes = list(notes or [])

    def list_research_notes(
        self, *, since: datetime | None = None
    ) -> list[LibraryResearchNote]:
        if since is None:
            return list(self._notes)
        bound = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        out: list[LibraryResearchNote] = []
        for note in self._notes:
            stamp = note.saved_at
            if stamp is None and note.source_date is not None:
                stamp = datetime(
                    note.source_date.year,
                    note.source_date.month,
                    note.source_date.day,
                    tzinfo=timezone.utc,
                )
            if stamp is None:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp >= bound:
                out.append(note)
        return out


class PrefilteredLibraryDigestReader:
    """Proey ``--library-json`` inject — already Research Note + since-last-run.

    Ignores the watermark ``since`` bound so Proey's pre-filtered payload is
    not emptied by a second filter (rows may omit ``saved_at``).
    """

    def __init__(self, notes: list[LibraryResearchNote] | None = None) -> None:
        self._notes = list(notes or [])

    def list_research_notes(
        self, *, since: datetime | None = None
    ) -> list[LibraryResearchNote]:
        return list(self._notes)

class LibraryDigestInput(BaseModel):
    """Bundled LIBRARY input for products (post Research Note filter)."""

    resource_type_filter: str = LIBRARY_RESOURCE_TYPE_FILTER
    notion_url: str = LIBRARY_NOTION_URL
    since: datetime | None = None
    notes: list[LibraryResearchNote] = Field(default_factory=list)
