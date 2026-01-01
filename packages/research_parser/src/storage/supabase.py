"""Supabase PostgreSQL client for storing parsed research."""

from datetime import datetime

import structlog
from supabase import Client, create_client
from tenacity import retry, stop_after_attempt, wait_exponential

from src.extraction.models import ExtractionResult

logger = structlog.get_logger()


class SupabaseClient:
    """Client for storing parsed research in Supabase PostgreSQL."""

    def __init__(self, url: str, key: str):
        self._client: Client = create_client(url, key)
        logger.info("Initialized Supabase client")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def insert_research(
        self,
        result: ExtractionResult,
        document_name: str,
    ) -> dict:
        """
        Insert parsed research into the database.

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

        # Insert into database
        record = {
            "parsed_data": parsed_data,
            "source_date": source_date,
            "source": result.metadata.source,
            "document_name": document_name,
        }

        logger.info(
            "Inserting research",
            document_name=document_name,
            source=result.metadata.source,
            source_date=source_date,
        )

        response = (
            self._client.table("parsed_research")
            .insert(record)
            .execute()
        )

        logger.info("Research inserted", document_name=document_name)
        return response.data[0] if response.data else {}
