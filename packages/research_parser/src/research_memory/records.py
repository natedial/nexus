"""Build durable research-memory records from parse artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from .spans import (
    build_figure_spans,
    build_paragraph_spans,
    build_retrieval_chunks,
    build_spans_from_blocks,
)

LIVE_PARSER_VERSION = "parser-source-v1"
LIVE_SPAN_VERSION = "span-v3"
LIVE_CHUNKER_VERSION = "retrieval-chunker-v3"


@dataclass
class ResearchArtifactContext:
    """Parse-time context persisted alongside parsed_research."""

    parser_version: str = LIVE_PARSER_VERSION
    parse_backend: str | None = None
    parse_confidence_score: float | None = None
    parse_confidence_status: str | None = None
    raw_markdown_path: str | None = None
    clean_text_path: str | None = None
    blocks_path: str | None = None
    figure_manifest: list[dict[str, Any]] = field(default_factory=list)
    artifact_manifest: dict[str, Any] = field(default_factory=dict)
    blocks: list | None = None
    span_version: str = LIVE_SPAN_VERSION
    chunker_version: str = LIVE_CHUNKER_VERSION
    ocr_retried: bool = False
    ocr_retry_reasons: list[str] = field(default_factory=list)
    source_page_count: int | None = None


def build_memory_records(
    *,
    research_id: int,
    document_hash: str,
    clean_text: str,
    context: ResearchArtifactContext | None = None,
    target_chars: int = 6000,
    min_chars: int = 1800,
    overlap_spans: int = 1,
) -> dict[str, Any]:
    """Build artifact, span, and chunk rows for a stored document."""
    context = context or ResearchArtifactContext()
    key_namespace = f"research:{research_id}:{document_hash}"
    if context.blocks:
        spans = build_spans_from_blocks(
            context.blocks,
            document_hash=document_hash,
            span_version=context.span_version,
            key_namespace=key_namespace,
        )
        source = "parser_blocks"
    else:
        spans = build_paragraph_spans(
            clean_text,
            document_hash=document_hash,
            span_version=context.span_version,
            key_namespace=key_namespace,
        )
        source = "parsed_research.full_text"

    spans.extend(
        build_figure_spans(
            context.figure_manifest,
            document_hash=document_hash,
            span_version=context.span_version,
            key_namespace=key_namespace,
            start_order=len(spans) + 1,
        )
    )

    chunks = build_retrieval_chunks(
        spans,
        document_hash=document_hash,
        chunker_version=context.chunker_version,
        key_namespace=key_namespace,
        target_chars=target_chars,
        min_chars=min_chars,
        overlap_spans=overlap_spans,
    )

    artifact_manifest = {
        "source": source,
        "span_version": context.span_version,
        "chunker_version": context.chunker_version,
        "block_count": len(context.blocks or []),
        **context.artifact_manifest,
    }
    if context.blocks_path:
        artifact_manifest["blocks_path"] = context.blocks_path

    artifact_record = {
        "research_id": research_id,
        "document_hash": document_hash,
        "parser_version": context.parser_version,
        "parse_backend": context.parse_backend,
        "parse_confidence_score": context.parse_confidence_score,
        "parse_confidence_status": context.parse_confidence_status,
        "raw_markdown_path": context.raw_markdown_path,
        "clean_text_path": context.clean_text_path,
        "figure_manifest": context.figure_manifest,
        "artifact_manifest": artifact_manifest,
        "clean_text_hash": _hash_text(clean_text),
    }

    span_records = []
    for span in spans:
        record = asdict(span)
        record.update(
            {
                "research_id": research_id,
                "section_path": list(span.section_path),
                "coordinates": span.coordinates,
                "metadata": dict(span.metadata) if span.metadata else {},
            }
        )
        span_records.append(record)

    chunk_records = []
    for chunk in chunks:
        record = asdict(chunk)
        record.update(
            {
                "research_id": research_id,
                "span_keys": list(chunk.span_keys),
                "chunk_type": "semantic",
                "token_count": max(1, len(chunk.text.split())),
                "embedding_model": None,
                "embedding_version": None,
                "embedding_id": None,
                "lexical_terms": [],
            }
        )
        chunk_records.append(record)

    return {
        "artifact": artifact_record,
        "spans": span_records,
        "chunks": chunk_records,
    }


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
