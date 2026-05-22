"""Build Supabase records for research memory substrate backfills."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from .spans import build_paragraph_spans, build_retrieval_chunks

DEFAULT_SPAN_VERSION = "span-v2"
DEFAULT_CHUNKER_VERSION = "retrieval-chunker-v2"
DEFAULT_PARSER_VERSION = "parser-backfill-v2"


def build_backfill_records(
    row: dict[str, Any],
    *,
    parser_version: str = DEFAULT_PARSER_VERSION,
    span_version: str = DEFAULT_SPAN_VERSION,
    chunker_version: str = DEFAULT_CHUNKER_VERSION,
    target_chars: int = 6000,
    min_chars: int = 1800,
    overlap_spans: int = 1,
) -> dict[str, list[dict[str, Any]] | dict[str, Any]]:
    """Build artifact, span, and retrieval chunk records from a parsed row."""

    research_id = _require_int(row.get("id"), "id")
    parsed_data = row.get("parsed_data")
    if not isinstance(parsed_data, dict):
        raise ValueError(f"research_id={research_id} parsed_data is not an object")
    full_text = parsed_data.get("full_text")
    if not isinstance(full_text, str) or not full_text.strip():
        raise ValueError(f"research_id={research_id} parsed_data.full_text is empty")

    clean_text = full_text.strip()
    clean_text_hash = _hash_text(clean_text)
    document_hash = _document_hash(row, clean_text)

    spans = build_paragraph_spans(
        clean_text,
        document_hash=document_hash,
        span_version=span_version,
        key_namespace=f"research:{research_id}:{document_hash}",
    )
    chunks = build_retrieval_chunks(
        spans,
        document_hash=document_hash,
        chunker_version=chunker_version,
        key_namespace=f"research:{research_id}:{document_hash}",
        target_chars=target_chars,
        min_chars=min_chars,
        overlap_spans=overlap_spans,
    )

    artifact_record = {
        "research_id": research_id,
        "document_hash": document_hash,
        "parser_version": parser_version,
        "parse_backend": "legacy_backfill",
        "parse_confidence_score": None,
        "parse_confidence_status": None,
        "raw_markdown_path": None,
        "clean_text_path": None,
        "figure_manifest": [],
        "artifact_manifest": {
            "source": "parsed_research.parsed_data.full_text",
            "span_version": span_version,
            "chunker_version": chunker_version,
        },
        "clean_text_hash": clean_text_hash,
    }

    span_records = []
    for span in spans:
        record = asdict(span)
        record.update(
            {
                "research_id": research_id,
                "section_path": list(span.section_path),
                "coordinates": None,
                "metadata": {},
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
                "token_count": _rough_token_count(chunk.text),
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


def _document_hash(row: dict[str, Any], text: str) -> str:
    value = row.get("document_hash")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _hash_text(text)


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
