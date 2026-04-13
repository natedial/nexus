"""Distill tool adapter for research corpus search."""

from typing import Any


class DistillAdapter:
    """Adapter for the distill_tool search API.

    Wraps distill_tool.api.search and corpus_info to provide
    a consistent interface for agent tool use.
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
        """Search the research corpus.

        Args:
            query: Search query string
            date_from: ISO date lower bound
            date_to: ISO date upper bound
            limit: Max results to return

        Returns:
            List of search results
        """
        pass

    def corpus_info(self) -> dict[str, Any]:
        """Get metadata about the research corpus.

        Returns:
            Dict with total_chunks, total_runs, date_range, sources
        """
        pass
