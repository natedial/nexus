"""Tests for retired corpus search adapter."""

import pytest

from research_analysis_layer.services.tools.distill_adapter import (
    CorpusSearchUnavailableError,
    DistillAdapter,
    create_distill_handlers,
)
from research_analysis_layer.services.tools.registry import ToolRegistry


class TestDistillAdapter:
    def test_search_fails_loudly_without_client(self) -> None:
        adapter = DistillAdapter()
        with pytest.raises(CorpusSearchUnavailableError, match="retired"):
            adapter.search("CPI")

    def test_corpus_info_fails_loudly_without_client(self) -> None:
        adapter = DistillAdapter()
        with pytest.raises(CorpusSearchUnavailableError, match="retired"):
            adapter.corpus_info()

    def test_registry_boots_with_relocated_schema(self) -> None:
        registry = ToolRegistry()
        assert registry.get_schema("research_search") is not None
        assert registry.get_schema("research_corpus_info") is not None

    def test_invoke_returns_error_when_corpus_retired(self) -> None:
        registry = ToolRegistry()
        handlers = create_distill_handlers()
        for name, handler in handlers.items():
            registry.register_handler(name, handler)

        result = registry.invoke("research_search", {"query": "CPI"})
        assert result["is_error"] is True
        assert "retired" in result["content"].lower()

    def test_client_override_still_works(self) -> None:
        class FakeClient:
            def search(self, query, **kwargs):
                return [{"chunk_id": "1", "text": "hit", "hybrid_score": 0.9}]

            def corpus_info(self):
                return {"total_chunks": 1}

        adapter = DistillAdapter(distill_client=FakeClient())
        results = adapter.search("CPI")
        assert len(results) == 1
        assert adapter.corpus_info()["total_chunks"] == 1
