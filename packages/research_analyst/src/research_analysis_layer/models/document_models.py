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
    document_id: str | None = None


@dataclass(slots=True)
class ParsedTheme:
    """One normalized extraction-service theme row.

    Parser no longer writes themes. These rows appear only after a later
    extraction service fills `research_themes`.
    """

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
    """One normalized extraction-service excerpt row."""

    id: int
    theme_id: int
    excerpt_order: int
    excerpt_text: str


@dataclass(slots=True)
class ParsedSpan:
    """One parser-owned span (`research_spans`, span-v3)."""

    span_key: str
    text: str
    span_kind: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    bbox: dict[str, Any] | None = None
    heading_path: list[str] = field(default_factory=list)
    span_id: str | None = None
    span_order: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedRetrievalChunk:
    """One parser-owned retrieval chunk (`research_retrieval_chunks`)."""

    chunk_key: str
    chunk_text: str
    span_keys: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    token_count: int | None = None
    heading_path: list[str] = field(default_factory=list)
    chunk_id: str | None = None
    chunk_order: int | None = None


@dataclass(slots=True)
class ParsedDocumentArtifacts:
    """Parser artifact row / `parsed_data.parse` mirror (`parser-source-v1`)."""

    parse_backend: str | None = None
    parser_version: str | None = None
    confidence_score: float | None = None
    confidence_status: str | None = None
    raw_markdown_path: str | None = None
    clean_text_path: str | None = None
    blocks_path: str | None = None
    artifact_manifest: dict[str, Any] | None = None
    figure_manifest: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class HydratedTheme:
    """Theme plus supporting excerpts."""

    theme: ParsedTheme
    excerpts: list[ParsedExcerpt] = field(default_factory=list)


@dataclass(slots=True)
class HydratedParsedDocument:
    """One parsed document plus spans, chunks, and optional extraction themes."""

    document: ParsedDocument
    themes: list[HydratedTheme]
    file_id: str | None = None
    spans: list[ParsedSpan] = field(default_factory=list)
    retrieval_chunks: list[ParsedRetrievalChunk] = field(default_factory=list)
    artifacts: ParsedDocumentArtifacts | None = None

    @property
    def research_id(self) -> int:
        return self.document.id

    @property
    def document_hash(self) -> str | None:
        return self.document.document_hash

    @property
    def ready_for_analysis(self) -> bool:
        """Parser fail-closed: a stored row should have spans or chunks.

        Legacy rows that still carry extraction themes (and a matching
        `theme_count`) remain analyzable without span tables.
        """
        if not self.document_hash:
            return False
        if self.spans or self.retrieval_chunks:
            return True
        if not self.themes:
            return False
        if self.document.theme_count > 0:
            return len(self.themes) == self.document.theme_count
        return True
