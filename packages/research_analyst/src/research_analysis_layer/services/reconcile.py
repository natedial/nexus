"""Reconciliation helpers."""

from __future__ import annotations

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.db.parsed_db_client import ParsedDbClient
from research_analysis_layer.db.state_db_reader import StateDbReader


def reconcile_recent(
    state_reader: StateDbReader,
    parsed_db_client: ParsedDbClient,
    store: AnalysisStore,
    analysis_version: str,
    limit: int,
) -> dict[str, int]:
    """Check parser-success rows against parsed DB presence and analysis coverage."""
    rows = state_reader.get_successful_since(None, limit=limit)
    matched = 0
    missing_parsed = 0
    analyzed = 0
    unanalyzed = 0
    for row in rows:
        document = parsed_db_client.fetch_document_by_file_id(row.file_id)
        if document is None:
            missing_parsed += 1
            continue
        matched += 1
        if store.has_analysis_for_document(
            research_id=document.id,
            document_hash=document.document_hash,
            analysis_version=analysis_version,
        ):
            analyzed += 1
        else:
            unanalyzed += 1
    return {
        "checked": len(rows),
        "matched_parsed_documents": matched,
        "missing_parsed_documents": missing_parsed,
        "analyzed_current_version": analyzed,
        "unanalyzed_current_version": unanalyzed,
    }
