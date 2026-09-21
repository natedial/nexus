"""Corpus search tool adapter (schema retained; corpus retired Phase 1)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SEARCH_RESULTS = 8
_MAX_EXCERPT_CHARS = 400

_CORPUS_RETIRED_MESSAGE = (
    "research_search corpus is retired with research-store (suite rationalization "
    "Phase 1). Canonical PostgreSQL retrieval lands in Phase 2/3. Enable Tholos "
    "(RESEARCH_ANALYST_THOLOS_ENABLED=true) or pass a test client to DistillAdapter."
)


class CorpusSearchUnavailableError(RuntimeError):
    """The legacy distilled corpus path is no longer available."""


class DistillAdapter:
    """Adapter for research_search / research_corpus_info tool handlers.

    Tool schemas still load from ``schemas/corpus_tool_schema.json`` so
    ``ToolRegistry`` boots. Invocations fail loudly until canonical retrieval
    replaces the retired research-store corpus.
    """

    def __init__(self, distill_client: Any | None = None):
        self._client = distill_client

    def search(
        self,
        query: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if self._client:
            return self._client.search(
                query,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        raise CorpusSearchUnavailableError(_CORPUS_RETIRED_MESSAGE)

    def corpus_info(self) -> dict[str, Any]:
        if self._client:
            return self._client.corpus_info()
        raise CorpusSearchUnavailableError(_CORPUS_RETIRED_MESSAGE)


def create_distill_handlers(
    adapter: DistillAdapter | None = None,
) -> dict[str, Any]:
    """Create tool handlers for corpus search tools."""
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
