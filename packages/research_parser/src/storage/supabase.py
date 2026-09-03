"""Supabase PostgreSQL client for storing parsed research."""

import hashlib
from datetime import datetime, timezone

import structlog
from supabase import Client, create_client
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.research_memory import (
    ResearchArtifactContext,
    build_memory_records,
    replace_memory_records,
)
from src.source import SourceDocument

logger = structlog.get_logger()


def _compute_document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SupabaseClient:
    """Persist parsed source documents and memory substrate rows."""

    def __init__(self, url: str, key: str):
        self._client: Client = create_client(url, key)
        logger.info("Initialized Supabase client")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_not_exception_type(ValueError),
        reraise=True,
    )
    def insert_research(
        self,
        source: SourceDocument,
        document_name: str,
        *,
        artifact_context: ResearchArtifactContext | None = None,
    ) -> dict:
        """Upsert parsed_research by Drive document_id, then write spans."""
        document_id = (source.document_id or "").strip()
        if not document_id:
            raise ValueError("document_id is required for parsed_research identity")

        source_date = source.source_date
        if not source_date or source_date in ("null", "undefined", ""):
            source_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        document_hash = _compute_document_hash(source.full_text)
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

        record = {
            "document_id": document_id,
            "parsed_data": parsed_data,
            "source_date": source_date,
            "source": source.source,
            "document_name": document_name,
            "document_title": source.document_title,
            "document_link": source.document_link,
            "document_hash": document_hash,
        }

        logger.info(
            "Inserting research",
            document_name=document_name,
            source=source.source,
            source_date=source_date,
        )

        research_row = self._get_or_create_research_row(
            document_id=document_id,
            record=record,
        )
        if not research_row:
            raise RuntimeError(f"Failed to persist research for {document_name}")

        research_id = research_row.get("id")
        if not research_id:
            raise RuntimeError(f"Persisted research row is missing id for {document_name}")

        self._persist_memory_substrate(
            research_id=int(research_id),
            document_hash=document_hash,
            clean_text=source.full_text,
            artifact_context=artifact_context,
        )
        return research_row

    def _persist_memory_substrate(
        self,
        *,
        research_id: int,
        document_hash: str,
        clean_text: str,
        artifact_context: ResearchArtifactContext | None,
    ) -> None:
        records = build_memory_records(
            research_id=research_id,
            document_hash=document_hash,
            clean_text=clean_text,
            context=artifact_context,
        )
        replace_memory_records(self._client, records)
        logger.info(
            "Research memory substrate persisted",
            research_id=research_id,
            span_count=len(records["spans"]),
            chunk_count=len(records["chunks"]),
            backend=(artifact_context.parse_backend if artifact_context else None),
        )

    def _get_or_create_research_row(
        self,
        document_id: str,
        record: dict,
    ) -> dict:
        upserted = (
            self._client.table("parsed_research")
            .upsert(
                record,
                on_conflict="document_id",
            )
            .execute()
        )
        if upserted.data:
            return upserted.data[0]

        fetched = (
            self._client.table("parsed_research")
            .select("*")
            .eq("document_id", document_id)
            .limit(1)
            .execute()
        )
        if not fetched.data:
            return {}
        return fetched.data[0]
