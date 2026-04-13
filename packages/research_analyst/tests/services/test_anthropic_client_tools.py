"""Tests for Anthropic client with tool use."""

import json
import pytest
from unittest.mock import patch, MagicMock
from research_analysis_layer.services.agent_llm_client import (
    AnthropicAgentLlmClient,
    AgentCallResult,
    ToolCallTrace,
    TokenUsage,
)


class TestAnthropicClientTools:
    """Test AnthropicAgentLlmClient tool use functionality."""

    def test_extract_text_from_content(self):
        """Test extracting text from Anthropic response content."""
        content = [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "World"},
            {"type": "tool_use", "name": "search", "input": {}},
        ]
        result = AnthropicAgentLlmClient._extract_text_from_content(content)
        assert result == "Hello \nWorld"

    def test_try_parse_json_valid(self):
        """Test parsing valid JSON."""
        text = '{"key": "value"}'
        result = AnthropicAgentLlmClient._try_parse_json(text)
        assert result == {"key": "value"}

    def test_try_parse_json_with_code_block(self):
        """Test parsing JSON from code block."""
        text = '```json\n{"key": "value"}\n```'
        result = AnthropicAgentLlmClient._try_parse_json(text)
        assert result == {"key": "value"}

    def test_try_parse_json_invalid(self):
        """Test parsing invalid JSON returns None."""
        text = "This is not JSON"
        result = AnthropicAgentLlmClient._try_parse_json(text)
        assert result is None

    def test_untool_models_denylist(self):
        """Test that untool models are denied tools."""
        client = AnthropicAgentLlmClient(api_key="test-key")
        assert "claude-haiku-4-20250514" in client.UNTOOL_MODELS

    @patch("urllib.request.urlopen")
    def test_generate_with_tools_happy_path(self, mock_urlopen):
        """Test tool use loop happy path - basic test with empty tools."""
        mock_response = {
            "content": [{"type": "text", "text": '{"result": "found"}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "Search for something"}],
            tools=[],
            model="claude-sonnet-4-20250514",
            max_tool_calls=4,
            timeout_seconds=60,
        )

        assert result.parsed_output == {"result": "found"}

    @patch("urllib.request.urlopen")
    def test_generate_with_tools_text_stop(self, mock_urlopen):
        """Test tool use loop stops with text."""
        mock_response = {
            "content": [{"type": "text", "text": '{"answer": "42"}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="You are a helpful assistant.",
            messages=[{"role": "user", "content": "What is the answer?"}],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "parameters": {"type": "object"},
                }
            ],
            model="claude-sonnet-4-20250514",
            max_tool_calls=4,
            timeout_seconds=60,
        )

        assert result.parsed_output == {"answer": "42"}
        assert result.stop_reason == "end_turn"

    @patch("urllib.request.urlopen")
    def test_token_usage_tracking(self, mock_urlopen):
        """Test token usage including cache fields is tracked."""
        mock_response = {
            "content": [{"type": "text", "text": '{"result": "ok"}'}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 25,
                "cache_creation_input_tokens": 10,
            },
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="Test",
            messages=[{"role": "user", "content": "test"}],
            tools=[],
            model="claude-sonnet-4-20250514",
            max_tool_calls=0,
            timeout_seconds=60,
        )

        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50
        assert result.token_usage.cache_read_input_tokens == 25
        assert result.token_usage.cache_creation_input_tokens == 10

    @patch("urllib.request.urlopen")
    def test_tool_budget_exhausted(self, mock_urlopen):
        """Test tool budget enforcement."""
        mock_response = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool1",
                    "name": "search",
                    "input": {"query": "test"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="Test",
            messages=[{"role": "user", "content": "test"}],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "parameters": {"type": "object"},
                }
            ],
            model="claude-sonnet-4-20250514",
            max_tool_calls=0,
            timeout_seconds=60,
        )

        assert "exhausted" in str(result.tool_calls[0].output_summary).lower()

    @patch("urllib.request.urlopen")
    def test_429_rate_limit_retry(self, mock_urlopen):
        """Test 429 rate limit triggers exponential backoff."""
        import urllib.error

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise urllib.error.HTTPError(
                    url="",
                    code=429,
                    msg="Rate Limited",
                    hdrs={},
                    fp=None,
                )
            mock_response = {
                "content": [{"type": "text", "text": '{"result": "ok"}'}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
            mock_file = MagicMock()
            mock_file.read.return_value = json.dumps(mock_response).encode()
            return mock_file

        mock_urlopen.side_effect = side_effect

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="Test",
            messages=[{"role": "user", "content": "test"}],
            tools=[],
            model="claude-sonnet-4-20250514",
            max_tool_calls=0,
            timeout_seconds=60,
        )

        assert result.parsed_output == {"result": "ok"}

    @patch("urllib.request.urlopen")
    def test_no_tools_for_untool_model(self, mock_urlopen):
        """Test that untool models don't use tools."""
        mock_response = {
            "content": [{"type": "text", "text": '{"result": "ok"}'}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        tool_registry = MagicMock()

        client = AnthropicAgentLlmClient(
            api_key="test-key", tool_registry=tool_registry
        )

        result = client.generate_with_tools(
            system_prompt="Test",
            messages=[{"role": "user", "content": "test"}],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "parameters": {"type": "object"},
                }
            ],
            model="claude-haiku-4-20250514",
            max_tool_calls=4,
            timeout_seconds=60,
        )

        tool_registry.invoke.assert_not_called()
        assert result.parsed_output == {"result": "ok"}
