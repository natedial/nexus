"""LIBRARY digest read path (Proey lock).

Canonical source: Notion LIBRARY database
Filter: Resource Type = Research Note only (same as existing 6:10 digest)
Link: https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9

Nexus products read through this protocol. Do not invent alternate channels.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

LIBRARY_NOTION_URL = "https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9"
LIBRARY_RESOURCE_TYPE_FILTER = "Research Note"


class LibraryResearchNote(BaseModel):
    """One LIBRARY row after the Research Note filter."""

    title: str
    note_id: str | None = None
    source_date: date | None = None
    summary: str = ""
    url: str | None = None


class LibraryDigestReader(Protocol):
    """Read path for LIBRARY digest inputs."""

    def list_research_notes(self) -> list[LibraryResearchNote]:
        """Return Research Note rows only (same filter as the 6:10 digest)."""
        ...


class FakeLibraryDigestReader:
    """Fixture-friendly LIBRARY reader — already filtered to Research Note."""

    def __init__(self, notes: list[LibraryResearchNote] | None = None) -> None:
        self._notes = list(notes or [])

    def list_research_notes(self) -> list[LibraryResearchNote]:
        return list(self._notes)


class LibraryDigestInput(BaseModel):
    """Bundled LIBRARY input for products (post Research Note filter)."""

    resource_type_filter: str = LIBRARY_RESOURCE_TYPE_FILTER
    notion_url: str = LIBRARY_NOTION_URL
    notes: list[LibraryResearchNote] = Field(default_factory=list)
