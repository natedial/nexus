"""Backfill helper functions."""

from __future__ import annotations

from research_analysis_layer.models import HydratedParsedDocument, ParserStateRecord


def synthesize_state_record(document: HydratedParsedDocument) -> ParserStateRecord:
    """Build a minimal parser-state-like record for manual backfills."""
    metadata = document.document.parsed_data.get("metadata", {}) if isinstance(document.document.parsed_data, dict) else {}
    file_id = document.file_id or metadata.get("document_id") or f"research:{document.research_id}"
    source_date = document.document.source_date or "1970-01-01"
    timestamp = f"{source_date}T00:00:00+00:00"
    from datetime import datetime

    return ParserStateRecord(
        file_id=file_id,
        file_name=document.document.document_name,
        status="completed",
        created_at=datetime.fromisoformat(timestamp),
        updated_at=datetime.fromisoformat(timestamp),
        parse_ok=True,
        boilerplate_ok=True,
        metadata_ok=True,
        themes_ok=True,
        trades_ok=True,
        storage_ok=True,
        error_message=None,
    )
