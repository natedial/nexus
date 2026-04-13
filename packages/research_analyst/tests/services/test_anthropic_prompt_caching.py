"""Tests for Anthropic prompt caching."""

import json
import pytest
from unittest.mock import patch, MagicMock
from research_analysis_layer.services.agent_llm_client import (
    AnthropicAgentLlmClient,
    TokenUsage,
)


class TestAnthropicPromptCaching:
    """Test Anthropic prompt caching functionality."""

    @patch("urllib.request.urlopen")
    def test_cache_creation_tokens_tracked(self, mock_urlopen):
        """Test that cache_creation_input_tokens is tracked on first call."""
        mock_response = {
            "content": [{"type": "text", "text": '{"result": "first"}'}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 80,
            },
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="Test prompt",
            messages=[{"role": "user", "content": "test"}],
            tools=[],
            model="claude-sonnet-4-20250514",
            max_tool_calls=0,
            timeout_seconds=60,
        )

        assert result.token_usage.cache_creation_input_tokens == 80
        assert result.token_usage.cache_read_input_tokens == 0

    @patch("urllib.request.urlopen")
    def test_cache_read_tokens_tracked(self, mock_urlopen):
        """Test that cache_read_input_tokens is tracked on cached call."""
        mock_response = {
            "content": [{"type": "text", "text": '{"result": "cached"}'}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 50,
                "output_tokens": 30,
                "cache_read_input_tokens": 45,
                "cache_creation_input_tokens": 0,
            },
        }

        mock_file = MagicMock()
        mock_file.read.return_value = json.dumps(mock_response).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_file

        client = AnthropicAgentLlmClient(api_key="test-key")

        result = client.generate_with_tools(
            system_prompt="Same test prompt as before",
            messages=[{"role": "user", "content": "test"}],
            tools=[],
            model="claude-sonnet-4-20250514",
            max_tool_calls=0,
            timeout_seconds=60,
        )

        assert result.token_usage.cache_read_input_tokens == 45
        assert result.token_usage.cache_creation_input_tokens == 0

    def test_cache_tokens_zero_when_not_present(self):
        """Test default values when cache tokens not present."""
        usage = TokenUsage()
        assert usage.cache_read_input_tokens == 0
        assert usage.cache_creation_input_tokens == 0

    def test_cache_tokens_accumulate(self):
        """Test that cache tokens can accumulate across calls."""
        usage1 = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=80,
        )
        usage2 = TokenUsage(
            input_tokens=50,
            output_tokens=30,
            cache_read_input_tokens=45,
            cache_creation_input_tokens=0,
        )

        total = TokenUsage(
            input_tokens=usage1.input_tokens + usage2.input_tokens,
            output_tokens=usage1.output_tokens + usage2.output_tokens,
            cache_read_input_tokens=usage1.cache_read_input_tokens
            + usage2.cache_read_input_tokens,
            cache_creation_input_tokens=usage1.cache_creation_input_tokens
            + usage2.cache_creation_input_tokens,
        )

        assert total.cache_read_input_tokens == 45
        assert total.cache_creation_input_tokens == 80
        assert total.input_tokens == 150
