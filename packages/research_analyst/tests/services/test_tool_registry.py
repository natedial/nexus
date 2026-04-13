"""Tests for tool registry."""

import pytest
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
        registry.load_schema(schema_file)

        schemas = registry.get_all_schemas()
        assert len(schemas) == 1
        assert schemas[0]["name"] == "tool_a"
