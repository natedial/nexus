"""Chunk and evidence draft models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AnalysisChunkDraft:
    """Bootstrap chunk representation."""

    chunk_order: int
    chunk_type: str
    title: str
    text: str
    section_name: str | None = None
    topic_tags: list[str] = field(default_factory=list)
    entity_tags: list[str] = field(default_factory=list)
    horizon_tag: str | None = None
    parser_theme_id: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    span_keys: list[str] = field(default_factory=list)
    retrieval_chunk_key: str | None = None


@dataclass(slots=True)
class EvidenceUnitDraft:
    """Bootstrap evidence unit representation."""

    chunk_order: int
    evidence_order: int
    evidence_type: str
    text: str
    normalized_text: str | None = None
    page_ref: str | None = None
    source_ref: dict[str, Any] = field(default_factory=dict)
    parser_theme_id: int | None = None
