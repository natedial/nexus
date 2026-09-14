"""Utilities for building the research memory substrate."""

from .persist import replace_memory_records
from .records import (
    LIVE_CHUNKER_VERSION,
    LIVE_PARSER_VERSION,
    LIVE_SPAN_VERSION,
    ResearchArtifactContext,
    build_memory_records,
)
from .spans import (
    RetrievalChunkDraft,
    SpanDraft,
    build_paragraph_spans,
    build_retrieval_chunks,
    build_spans_from_blocks,
)

__all__ = [
    "LIVE_CHUNKER_VERSION",
    "LIVE_PARSER_VERSION",
    "LIVE_SPAN_VERSION",
    "ResearchArtifactContext",
    "RetrievalChunkDraft",
    "SpanDraft",
    "build_memory_records",
    "build_paragraph_spans",
    "build_retrieval_chunks",
    "build_spans_from_blocks",
    "replace_memory_records",
]
