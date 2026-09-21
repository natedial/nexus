"""Source document persistence interface for parsed research."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from src.research_memory import ResearchArtifactContext
from src.source import SourceDocument


def compute_document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SourceStore(ABC):
    """Persist parsed source documents and memory substrate rows."""

    @abstractmethod
    def insert_research(
        self,
        source: SourceDocument,
        document_name: str,
        *,
        artifact_context: ResearchArtifactContext | None = None,
    ) -> dict:
        """Upsert parsed_research by Drive document_id, then write spans."""


def build_parsed_research_record(
    source: SourceDocument,
    document_name: str,
    *,
    artifact_context: ResearchArtifactContext | None = None,
) -> dict:
    """Build the parsed_research row payload for insert/upsert."""
    document_id = (source.document_id or "").strip()
    if not document_id:
        raise ValueError("document_id is required for parsed_research identity")

    source_date = source.source_date
    if not source_date or source_date in ("null", "undefined", ""):
        source_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    document_hash = compute_document_hash(source.full_text)
    parsed_data = {
        "full_text": source.full_text,
        "identity": {
            "document_id": document_id,
            "document_uri": source.document_uri,
            "document_link": source.document_link,
            "source": source.source,
            "source_date": source_date,
        },
    }
    if artifact_context is not None:
        parsed_data["parse"] = {
            "backend": artifact_context.parse_backend,
            "parser_version": artifact_context.parser_version,
            "confidence_score": artifact_context.parse_confidence_score,
            "confidence_status": artifact_context.parse_confidence_status,
            "ocr_retried": artifact_context.ocr_retried,
            "ocr_retry_reasons": list(artifact_context.ocr_retry_reasons),
            "source_page_count": artifact_context.source_page_count,
            "raw_markdown_path": artifact_context.raw_markdown_path,
            "clean_text_path": artifact_context.clean_text_path,
            "blocks_path": artifact_context.blocks_path,
        }

    return {
        "document_id": document_id,
        "parsed_data": parsed_data,
        "source_date": source_date,
        "source": source.source,
        "document_name": document_name,
        "document_title": source.document_title,
        "document_link": source.document_link,
        "document_hash": document_hash,
    }
