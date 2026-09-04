"""Backfill helper functions."""

from __future__ import annotations

from datetime import datetime

from research_analysis_layer.models import HydratedParsedDocument, ParserStateRecord
from research_analysis_layer.parsed_payload import file_id_from_payload


def synthesize_state_record(document: HydratedParsedDocument) -> ParserStateRecord:
    """Build a minimal parser-state-like record for manual backfills."""
    file_id = file_id_from_payload(
        document.document.parsed_data,
        document_link=document.document.document_link,
        explicit_file_id=document.file_id,
        document_id=document.document.document_id,
    ) or f"research:{document.research_id}"
    source_date = document.document.source_date or "1970-01-01"
    timestamp = f"{source_date}T00:00:00+00:00"

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
