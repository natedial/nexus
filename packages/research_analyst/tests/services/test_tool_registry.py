"""Tests for tool registry."""

import pytest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from research_analysis_layer.services.tools.registry import ToolRegistry


class TestToolRegistry:
    """Test ToolRegistry functionality."""

    def test_load_schema(self, tmp_path):
        """Test loading tool schemas from JSON file."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        assert "test_tool" in registry.list_tools()
        schema = registry.get_schema("test_tool")
        assert schema["name"] == "test_tool"

    def test_register_handler(self, tmp_path):
        """Test registering a tool handler."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        def handler(input_data):
            return {"result": f"processed: {input_data.get('query')}"}

        registry.register_handler("test_tool", handler)

        result = registry.invoke("test_tool", {"query": "hello"})
        assert result["is_error"] is False
        assert result["content"]["result"] == "processed: hello"

    def test_validate_input_valid(self, tmp_path):
        """Test input validation with valid input."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        is_valid, error = registry.validate_input("test_tool", {"query": "hello"})
        assert is_valid is True
        assert error == ""

    def test_validate_input_missing_required(self, tmp_path):
        """Test input validation with missing required field."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        is_valid, error = registry.validate_input("test_tool", {"other": "value"})
        assert is_valid is False
        assert "Missing required field" in error

    def test_validate_input_rejects_unknown_fields(self, tmp_path):
        """Test input validation rejects unknown fields."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        is_valid, error = registry.validate_input(
            "test_tool", {"query": "hello", "extra": "nope"}
        )
        assert is_valid is False
        assert "Unknown field" in error

    def test_validate_input_enforces_pattern_and_numeric_bounds(self, tmp_path):
        """Test schema validation enforces patterns and numeric bounds."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "search_tool", "description": "A search tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "date_from": {"type": "string", "pattern": "^\\\\d{4}-\\\\d{2}-\\\\d{2}$"}, "limit": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        is_valid, error = registry.validate_input(
            "search_tool", {"query": "hello", "date_from": "2026/04/13", "limit": 99}
        )
        assert is_valid is False
        assert "date_from" in error or "limit" in error

    def test_invoke_error_handler(self, tmp_path):
        """Test tool invocation error handling."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        def failing_handler(input_data):
            raise ValueError("Something went wrong")

        registry.register_handler("test_tool", failing_handler)

        result = registry.invoke("test_tool", {"query": "hello"})
        assert result["is_error"] is True
        assert "Something went wrong" in result["content"]

    def test_invoke_unknown_tool(self, tmp_path):
        """Test invoking an unknown tool."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("[]")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        result = registry.invoke("unknown_tool", {})
        assert result["is_error"] is True

    def test_invoke_timeout(self, tmp_path):
        """Test tool invocation timeout."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "slow_tool", "description": "A slow tool", "parameters": {"type": "object", "properties": {}}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        def slow_handler(input_data):
            import time

            time.sleep(2)
            return {"result": "done"}

        registry.register_handler("slow_tool", slow_handler)

        result = registry.invoke("slow_tool", {}, timeout=0.1)
        assert result["is_error"] is True
        assert "timed out" in result["content"]

    def test_invoke_respects_shared_budget_across_threads(self, tmp_path):
        """Shared invocation budget is enforced atomically across threads."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "limited_tool", "description": "A limited tool", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)
        seen_queries: list[str] = []

        def handler(input_data):
            seen_queries.append(input_data["query"])
            return {"result": input_data["query"]}

        registry.register_handler("limited_tool", handler)
        registry.set_invocation_budget(1)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    registry.invoke, "limited_tool", {"query": f"q{idx}"}
                )
                for idx in range(2)
            ]
            results = [future.result() for future in futures]

        assert len(seen_queries) == 1
        assert sum(1 for result in results if result["is_error"]) == 1
        assert any(
            "budget exhausted" in result["content"].lower()
            for result in results
            if result["is_error"]
        )

    def test_list_tools(self, tmp_path):
        """Test listing all tools."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "tool_a", "description": "Tool A", "parameters": {"type": "object", "properties": {}}},
            {"name": "tool_b", "description": "Tool B", "parameters": {"type": "object", "properties": {}}}
        ]""")

        registry = ToolRegistry()
        registry.load_schema(schema_file)

        tools = registry.list_tools()
        assert "tool_a" in tools
        assert "tool_b" in tools

    def test_get_all_schemas(self, tmp_path):
        """Test getting all tool schemas."""
        schema_file = tmp_path / "test_schema.json"
        schema_file.write_text("""[
            {"name": "tool_a", "description": "Tool A", "parameters": {"type": "object", "properties": {}}}
        ]""")

        registry = ToolRegistry()
        registry._schemas.clear()
        registry.load_schema(schema_file)

        schemas = registry.get_all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "tool_a"
