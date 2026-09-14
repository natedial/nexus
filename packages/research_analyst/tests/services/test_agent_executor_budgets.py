"""Tests for agent executor budget controls."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path

from research_analysis_layer.services.tools.registry import ToolRegistry
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
    ToolCallTrace,
)


class TestToolRegistryBudgets:
    """Test budget enforcement in ToolRegistry."""

    @pytest.fixture
    def tool_registry(self, tmp_path):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            '[{"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}]'
        )
        registry = ToolRegistry(schema_path=schema_path)

        def mock_handler(input_data):
            return {"result": f"processed {input_data.get('query')}"}

        registry.register_handler("test_tool", mock_handler)
        return registry

    def test_budget_exhausted_blocks_tool_calls(self, tool_registry):
        tool_registry.set_invocation_budget(0)
        result = tool_registry.invoke("test_tool", {"query": "test"})
        assert result["is_error"] is True
        assert "exhausted" in result["content"].lower()

    def test_budget_decremented_on_each_invocation(self, tool_registry):
        tool_registry.set_invocation_budget(2)
        result1 = tool_registry.invoke("test_tool", {"query": "first"})
        assert result1["is_error"] is False
        result2 = tool_registry.invoke("test_tool", {"query": "second"})
        assert result2["is_error"] is False
        result3 = tool_registry.invoke("test_tool", {"query": "third"})
        assert result3["is_error"] is True

    def test_budget_cleared_after_success(self, tool_registry):
        tool_registry.set_invocation_budget(1)
        tool_registry.invoke("test_tool", {"query": "test"})
        with tool_registry._budget_lock:
            assert tool_registry._remaining_invocations == 0
        tool_registry.clear_invocation_budget()
        with tool_registry._budget_lock:
            assert tool_registry._remaining_invocations is None

    def test_budget_cleared_after_failure(self, tool_registry):
        tool_registry.set_invocation_budget(2)
        tool_registry.invoke("test_tool", {"query": "first"})
        tool_registry.clear_invocation_budget()
        with tool_registry._budget_lock:
            assert tool_registry._remaining_invocations is None

    def test_none_budget_allows_unlimited_calls(self, tool_registry):
        tool_registry.set_invocation_budget(None)
        for _ in range(10):
            result = tool_registry.invoke("test_tool", {"query": "test"})
            assert result["is_error"] is False


class TestBudgetEnforcement:
    """Additional budget enforcement tests."""

    def test_budget_can_be_set_multiple_times(self, tmp_path):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            '[{"name": "test_tool", "description": "Test", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]'
        )
        registry = ToolRegistry(schema_path=schema_path)
        registry.register_handler("test_tool", lambda x: x)

        registry.set_invocation_budget(1)
        assert registry._remaining_invocations == 1

        registry.set_invocation_budget(5)
        assert registry._remaining_invocations == 5

    def test_budget_tracks_remaining_across_multiple_tools(self, tmp_path):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            '[{"name": "tool_a", "description": "Tool A", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}, {"name": "tool_b", "description": "Tool B", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]'
        )
        registry = ToolRegistry(schema_path=schema_path)

        def handler_a(input_data):
            return {"result": "a"}

        def handler_b(input_data):
            return {"result": "b"}

        registry.register_handler("tool_a", handler_a)
        registry.register_handler("tool_b", handler_b)

        registry.set_invocation_budget(3)

        assert registry.invoke("tool_a", {"q": "1"})["is_error"] is False
        assert registry.invoke("tool_b", {"q": "2"})["is_error"] is False
        assert registry.invoke("tool_a", {"q": "3"})["is_error"] is False
        assert registry.invoke("tool_b", {"q": "4"})["is_error"] is True

    def test_error_result_includes_budget_message(self, tmp_path):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            '[{"name": "test_tool", "description": "Test", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]'
        )
        registry = ToolRegistry(schema_path=schema_path)
        registry.register_handler("test_tool", lambda x: x)

        registry.set_invocation_budget(0)
        result = registry.invoke("test_tool", {"q": "test"})

        assert result["is_error"] is True
        assert "budget" in result["content"].lower()

    def test_concurrent_budget_consumption(self, tmp_path):
        import threading

        schema_path = tmp_path / "schema.json"
        schema_path.write_text(
            '[{"name": "test_tool", "description": "Test", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}]'
        )
        registry = ToolRegistry(schema_path=schema_path)
        registry.register_handler("test_tool", lambda x: {"result": "ok"})

        registry.set_invocation_budget(5)
        results = []

        def try_invoke():
            result = registry.invoke("test_tool", {"q": "test"})
            results.append(result["is_error"])

        threads = [threading.Thread(target=try_invoke) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) >= 5
