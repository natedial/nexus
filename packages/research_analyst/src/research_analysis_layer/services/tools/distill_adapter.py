"""Distill tool adapter for research corpus search."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CORPUS_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_DB_PATH = _CORPUS_ROOT / "research-store" / "data" / "distilled_corpus.db"
_MAX_SEARCH_RESULTS = 8
_MAX_EXCERPT_CHARS = 400


class DistillAdapter:
    """Adapter for the distill_tool search API.

    Wraps distill_tool.api.search and corpus_info to provide
    a consistent interface for agent tool use.
    """

    def __init__(
        self,
        distill_client: Any | None = None,
        db_path: Path | None = None,
    ):
        self._client = distill_client
        self._db_path = db_path or _get_default_db_path()

    def search(
        self,
        query: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the research corpus.

        Args:
            query: Search query string
            date_from: ISO date lower bound
            date_to: ISO date upper bound
            limit: Max results to return

        Returns:
            List of search results with chunk_id, source_path, source_date,
            text, keywords, lexical_score, semantic_score, hybrid_score
        """
        if self._client:
            return self._client.search(
                query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )

        try:
            from distill_tool.api import search as distill_search

            return distill_search(
                query,
                db_path=str(self._db_path),
                limit=limit,
                date_from=date_from,
                date_to=date_to,
            )
        except ImportError as e:
            logger.warning("distill_tool not available: %s", e)
            return []

    def corpus_info(self) -> dict[str, Any]:
        """Get metadata about the research corpus.

        Returns:
            Dict with total_chunks, total_runs, date_range, sources
        """
        if self._client:
            return self._client.corpus_info()

        try:
            from distill_tool.api import corpus_info as distill_corpus_info

            return distill_corpus_info(str(self._db_path))
        except ImportError as e:
            logger.warning("distill_tool not available: %s", e)
            return {
                "total_chunks": 0,
                "total_runs": 0,
                "date_range": None,
                "sources": [],
            }


def _get_default_db_path() -> Path:
    """Get the default path to the distilled corpus database."""
    env_path = os.getenv("DISTILL_DB_PATH")
    if env_path:
        return Path(env_path)
    return _DEFAULT_DB_PATH


def create_distill_handlers(
    adapter: DistillAdapter | None = None,
) -> dict[str, Any]:
    """Create tool handlers for the DistillAdapter.

    Returns a dict mapping tool names to handler functions
    that can be registered with ToolRegistry.
    """
    adapter = adapter or DistillAdapter()

    def handle_search(input_data: dict[str, Any]) -> list[dict[str, Any]]:
        results = adapter.search(
            input_data.get("query", ""),
            date_from=input_data.get("date_from"),
            date_to=input_data.get("date_to"),
            limit=input_data.get("limit", 10),
        )
        return _sanitize_search_results(results)

    def handle_corpus_info(input_data: dict[str, Any]) -> dict[str, Any]:
        return adapter.corpus_info()

    return {
        "research_search": handle_search,
        "research_corpus_info": handle_corpus_info,
    }


def _sanitize_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce search results to a bounded, untrusted evidence payload."""
    sanitized: list[dict[str, Any]] = []
    for item in results[:_MAX_SEARCH_RESULTS]:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "chunk_id": item.get("chunk_id"),
                "source_path": item.get("source_path"),
                "source_date": item.get("source_date"),
                "page_number": item.get("page_number"),
                "text_excerpt": _truncate_excerpt(item.get("text")),
                "hybrid_score": item.get("hybrid_score"),
                "lexical_score": item.get("lexical_score"),
                "semantic_score": item.get("semantic_score"),
            }
        )
    return sanitized


def _truncate_excerpt(value: Any) -> str:
    """Bound untrusted corpus text before returning it to the model."""
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) > _MAX_EXCERPT_CHARS:
        text = text[:_MAX_EXCERPT_CHARS].rstrip() + "..."
    return text
