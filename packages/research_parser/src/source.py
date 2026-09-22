"""Parse-and-store document record."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceDocument:
    """Durable source captured from a Drive PDF."""

    document_id: str
    document_name: str
    full_text: str
    source: str | None = None
    source_date: str | None = None
    document_uri: str | None = None
    document_link: str | None = None
    relay_key: str | None = None

    @property
    def document_title(self) -> str:
        name = self.document_name.rsplit(".", 1)[0]
        return name or self.document_name
