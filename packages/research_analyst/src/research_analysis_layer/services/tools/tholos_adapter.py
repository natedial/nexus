"""Tholos adapter for research corpus search."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class TholosAdapter:
    """HTTP adapter for the external sophia_tholos service.

    Provides a synchronous interface to the Tholos research search API.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8004",
        timeout_seconds: int = 30,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def search(
        self,
        query: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        keyword_weight: float | None = None,
        semantic_weight: float | None = None,
    ) -> list[dict[str, Any]]:
        """Search the research corpus.

        Args:
            query: Search query string
            date_from: ISO date lower bound (optional)
            date_to: ISO date upper bound (optional)
            limit: Max results to return
            keyword_weight: Lexical relevance weight (0.0-1.0)
            semantic_weight: Semantic relevance weight (0.0-1.0)

        Returns:
            List of search results with chunk_id, source_path, text, scores

        Raises:
            httpx.HTTPError: If the request fails
        """
        body: dict[str, Any] = {"query": query, "limit": limit}

        if date_from:
            body["date_from"] = date_from
        if date_to:
            body["date_to"] = date_to
        if keyword_weight is not None:
            body["keyword_weight"] = keyword_weight
        if semantic_weight is not None:
            body["semantic_weight"] = semantic_weight

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self._base_url}/search", json=body)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                for item in results:
                    if "source_date" not in item:
                        item["source_date"] = None

                return results

        except httpx.TimeoutException:
            raise httpx.HTTPError("Tholos request timed out")
        except httpx.ConnectError as e:
            raise httpx.HTTPError(f"Could not connect to Tholos: {e}")

    def corpus_info(self) -> dict[str, Any]:
        """Get metadata about the research corpus.

        Returns:
            Dict with total_chunks, date_range (null - Tholos doesn't expose), sources

        Note:
            date_range is returned as None because Tholos does not expose
            this endpoint. This is a known limitation documented in the
            Tholos integration plan.

        Raises:
            httpx.HTTPError: If the request fails
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                health_response = client.get(f"{self._base_url}/ready")
                health_response.raise_for_status()
                health_data = health_response.json()

                sources_response = client.get(f"{self._base_url}/sources")
                sources_response.raise_for_status()
                sources_data = sources_response.json()

                total_chunks = health_data.get("total_chunks", 0)

                sources = sources_data.get("sources", [])
                source_list = []
                for s in sources:
                    source_list.append(
                        {
                            "source_path": s.get("source_path", ""),
                            "chunk_count": s.get("chunk_count", 0),
                        }
                    )

                return {
                    "total_chunks": total_chunks,
                    "total_runs": health_data.get("total_runs", 0),
                    "date_range": None,
                    "sources": source_list,
                }

        except httpx.TimeoutException:
            raise httpx.HTTPError("Tholos request timed out")
        except httpx.ConnectError as e:
            raise httpx.HTTPError(f"Could not connect to Tholos: {e}")


def create_tholos_handlers(
    adapter: TholosAdapter | None = None,
) -> dict[str, Any]:
    """Create tool handlers for the TholosAdapter.

    Returns a dict mapping tool names to handler functions
    that can be registered with ToolRegistry.
    """
    adapter = adapter or TholosAdapter()

    def handle_search(input_data: dict[str, Any]) -> list[dict[str, Any]]:
        return adapter.search(
            input_data.get("query", ""),
            date_from=input_data.get("date_from"),
            date_to=input_data.get("date_to"),
            limit=input_data.get("limit", 10),
            keyword_weight=input_data.get("keyword_weight"),
            semantic_weight=input_data.get("semantic_weight"),
        )

    def handle_corpus_info(input_data: dict[str, Any]) -> dict[str, Any]:
        return adapter.corpus_info()

    return {
        "research_search": handle_search,
        "research_corpus_info": handle_corpus_info,
    }
