"""Idempotent writes for research-memory substrate rows."""

from __future__ import annotations

from typing import Any


def replace_memory_records(client: Any, records: dict[str, Any]) -> None:
    """Replace artifact/span/chunk rows for the record versions, then insert."""
    artifact = records["artifact"]
    research_id = artifact["research_id"]
    parser_version = artifact["parser_version"]
    span_version = artifact["artifact_manifest"]["span_version"]
    chunker_version = artifact["artifact_manifest"]["chunker_version"]

    client.table("research_document_artifacts").delete().eq("research_id", research_id).eq(
        "parser_version", parser_version
    ).execute()
    client.table("research_retrieval_chunks").delete().eq("research_id", research_id).eq(
        "chunker_version", chunker_version
    ).execute()
    client.table("research_spans").delete().eq("research_id", research_id).eq(
        "span_version", span_version
    ).execute()

    client.table("research_document_artifacts").upsert(
        artifact,
        on_conflict="research_id,parser_version",
    ).execute()

    spans = records["spans"]
    if spans:
        client.table("research_spans").upsert(spans, on_conflict="span_key").execute()

    chunks = records["chunks"]
    if chunks:
        client.table("research_retrieval_chunks").upsert(
            chunks,
            on_conflict="chunk_key",
        ).execute()
