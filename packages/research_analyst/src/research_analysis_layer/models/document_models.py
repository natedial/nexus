"""Parsed document models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedDocument:
    """One row from parser-owned parsed_research."""

    id: int
    document_name: str
    source: str | None
    source_date: str | None
    parsed_data: dict[str, Any]
    document_title: str | None = None
    publisher: str | None = None
    area: str | None = None
    region: str | None = None
    asset_focus: str | None = None
    document_link: str | None = None
    theme_count: int = 0
    trade_count: int = 0
    document_hash: str | None = None


@dataclass(slots=True)
class ParsedTheme:
    """One normalized parser-owned theme row."""

    id: int
    research_id: int
    theme_order: int
    label: str
    scope: str | None
    primary_category: str | None
    relevance: list[str]
    classification: str
    strength: str
    confidence: str
    evidence_count: int
    mention_count: int
    context: str
    directionality: dict[str, Any] | None
    argument_structure: dict[str, Any] | None


@dataclass(slots=True)
class ParsedExcerpt:
    """One normalized parser-owned excerpt row."""

    id: int
    theme_id: int
    excerpt_order: int
    excerpt_text: str


@dataclass(slots=True)
class HydratedTheme:
    """Theme plus supporting excerpts."""

    theme: ParsedTheme
    excerpts: list[ParsedExcerpt] = field(default_factory=list)


@dataclass(slots=True)
class HydratedParsedDocument:
    """One parsed document plus its themes and excerpts."""

    document: ParsedDocument
    themes: list[HydratedTheme]
    file_id: str | None = None

    @property
    def research_id(self) -> int:
        return self.document.id

    @property
    def document_hash(self) -> str | None:
        return self.document.document_hash

    @property
    def ready_for_analysis(self) -> bool:
        if not self.document_hash:
            return False
        if self.document.theme_count <= 0:
            return False
        return len(self.themes) == self.document.theme_count
