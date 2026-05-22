"""Supabase PostgreSQL client for storing parsed research."""

import hashlib
from datetime import datetime

import structlog
from supabase import Client, create_client
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.extraction.models import ExtractionResult, Theme

logger = structlog.get_logger()


def _compute_document_hash(text: str) -> str:
    """Compute SHA256 hash of cleaned text for idempotent backfill."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SupabaseClient:
    """Client for storing parsed research in Supabase PostgreSQL."""

    def __init__(self, url: str, key: str):
        self._client: Client = create_client(url, key)
        logger.info("Initialized Supabase client")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_not_exception_type(ValueError),
    )
    def insert_research(
        self,
        result: ExtractionResult,
        document_name: str,
    ) -> dict:
        """
        Insert parsed research into the database.

        Dual-write pattern:
        - parsed_data: JSONB with all extraction results (archival)
        - Normalized tables: research_themes, research_theme_excerpts, research_theme_links (queryable)

        Matches the schema from the n8n workflow:
        - parsed_data: JSONB with all extraction results
        - source_date: publication date
        - source: research firm name
        - document_name: original file name
        """
        # Build the parsed_data JSON structure
        # Note: through_lines and callouts are now synthesized downstream
        parsed_data = {
            "metadata": result.metadata.model_dump(),
            "themes": [t.model_dump() for t in result.themes],
            "trades": [t.model_dump() for t in result.trades],
            "full_text": result.full_text,
            "extraction_stats": {
                "num_themes": len(result.themes),
                "num_trades": len(result.trades),
                "extraction_method": "LLM-based extraction",
                "metadata_ok": result.metadata_ok,
                "themes_ok": result.themes_ok,
                "trades_ok": result.trades_ok,
            },
        }

        # Determine source_date
        source_date = result.metadata.source_date
        if not source_date or source_date in ("null", "undefined", ""):
            source_date = datetime.utcnow().strftime("%Y-%m-%d")

        # Build document title
        # Note: title synthesis now happens downstream
        document_title = f"Analysis of {result.metadata.source}"

        # Compute document hash from cleaned text
        document_hash = _compute_document_hash(result.full_text)
        document_id = (result.metadata.document_id or "").strip()
        if not document_id:
            raise ValueError("metadata.document_id is required for parsed_research identity")

        # Build document-level record with normalized columns
        record = {
            "document_id": document_id,
            "parsed_data": parsed_data,
            "source_date": source_date,
            "source": result.metadata.source,
            "document_name": document_name,
            # New normalized columns
            "document_title": document_title,
            "publisher": result.metadata.publisher,
            "area": result.metadata.area,
            "region": result.metadata.region,
            "asset_focus": result.metadata.asset_focus,
            "document_link": result.metadata.document_link,
            "theme_count": len(result.themes),
            "trade_count": len(result.trades),
            "document_hash": document_hash,
            "index_status": "pending",
            "indexed_at": None,
            "index_error": None,
            "index_version": None,
            "indexing_batch_id": None,
        }

        logger.info(
            "Inserting research",
            document_name=document_name,
            source=result.metadata.source,
            source_date=source_date,
            theme_count=len(result.themes),
            trade_count=len(result.trades),
        )

        research_row = self._get_or_create_research_row(
            document_id=document_id,
            record=record,
        )
        if not research_row:
            logger.error("Failed to persist research", document_name=document_name)
            return {}

        research_id = research_row.get("id")
        logger.info(
            "Research persisted",
            document_name=document_name,
            research_id=research_id,
        )

        if research_id:
            self._replace_normalized_themes(research_id, result.themes)

        return research_row

    def _get_or_create_research_row(
        self,
        document_id: str,
        record: dict,
    ) -> dict:
        """Upsert the document row using the dedupe key enforced in SQL."""
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

    def _replace_normalized_themes(self, research_id: int, themes: list[Theme]) -> None:
        """Replace normalized theme rows for a document."""
        self._client.table("research_themes").delete().eq("research_id", research_id).execute()
        if not themes:
            logger.info("Normalized themes cleared", research_id=research_id)
            return

        for idx, theme in enumerate(themes, start=1):
            # Insert theme
            theme_record = {
                "research_id": research_id,
                "theme_order": idx,
                "label": theme.label,
                "scope": None,
                "primary_category": theme.relevance[0] if theme.relevance else None,
                "relevance": theme.relevance,
                "classification": theme.classification,
                "strength": theme.strength,
                "confidence": theme.confidence,
                "evidence_count": len(theme.excerpts),
                "mention_count": theme.mention_count,
                "context": theme.context,
                "directionality": theme.directionality,
                "argument_structure": (
                    theme.argument_structure.model_dump() if theme.argument_structure else None
                ),
            }

            theme_response = self._client.table("research_themes").insert(theme_record).execute()

            if theme_response.data:
                theme_id = theme_response.data[0].get("id")
                # Insert excerpts
                for excerpt_idx, excerpt in enumerate(theme.excerpts, start=1):
                    self._client.table("research_theme_excerpts").insert(
                        {
                            "theme_id": theme_id,
                            "excerpt_order": excerpt_idx,
                            "excerpt_text": excerpt.text,
                        }
                    ).execute()

        logger.info(
            "Normalized themes inserted",
            research_id=research_id,
            theme_count=len(themes),
        )
