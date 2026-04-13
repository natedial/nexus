"""Hydration helper for parser outputs."""

from __future__ import annotations

from research_analysis_layer.db.parsed_db_client import ParsedDbClient
from research_analysis_layer.models import HydratedParsedDocument, ParserStateRecord


class Hydrator:
    """Translate upstream state records into hydrated parsed documents."""

    def __init__(self, parsed_db_client: ParsedDbClient):
        self.parsed_db_client = parsed_db_client

    def hydrate_from_state(self, record: ParserStateRecord) -> HydratedParsedDocument | None:
        return self.parsed_db_client.hydrate_by_file_id(record.file_id)

    def hydrate_by_research_id(self, research_id: int) -> HydratedParsedDocument | None:
        docs = self.parsed_db_client.hydrate_documents([research_id])
        if not docs:
            return None
        return docs[0]

    def hydrate_by_document_hash(self, document_hash: str) -> HydratedParsedDocument | None:
        doc = self.parsed_db_client.fetch_document_by_hash(document_hash)
        if doc is None:
            return None
        metadata = doc.parsed_data.get("metadata", {}) if isinstance(doc.parsed_data, dict) else {}
        file_id = metadata.get("document_id")
        return self.parsed_db_client.hydrate_document(doc, file_id=file_id)
