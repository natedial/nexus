"""Tests for OpenAI-compatible agent LLM client."""

import json
import pytest
from unittest.mock import patch, MagicMock

from research_analysis_layer.services.agent_llm_client import (
    OpenAICompatibleAgentLlmClient,
    AgentCallResult,
    TokenUsage,
    build_agent_llm_client,
    _try_parse_json,
)
from research_analysis_layer.config import Settings


def _mock_urlopen(response_body: dict):
    """Return a context-manager mock that yields the given response body."""
    mock_file = MagicMock()
    mock_file.read.return_value = json.dumps(response_body).encode()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_file
    mock_cm.__exit__.return_value = False
    return mock_cm


def _text_resp(content: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def _tool_call_resp(tool_calls: list[dict]) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110},
    }


class TestTryParseJson:
    def test_parses_fenced_json(self):
        assert _try_parse_json('```json\n{"ok": true}\n```') == {"ok": True}

    def test_returns_none_for_non_json(self):
        assert _try_parse_json("not json") is None


class TestOpenAIClientInit:
    def test_default_base_url(self):
        c = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        assert c.base_url == "https://api.openai.com"

    def test_custom_base_url_strips_slash(self):
        c = OpenAICompatibleAgentLlmClient(
            api_key="sk-test", base_url="http://localhost:11434/"
        )
        assert c.base_url == "http://localhost:11434"

    def test_openai_mode_uses_max_completion_tokens(self):
        c = OpenAICompatibleAgentLlmClient(
            api_key="sk-test",
            use_max_completion_tokens=True,
        )
        body = c._build_request_body(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert body["max_completion_tokens"] == 16384
        assert "max_tokens" not in body
        assert body["reasoning_effort"] == "low"

    def test_gpt5_reasoning_effort_can_be_overridden(self):
        c = OpenAICompatibleAgentLlmClient(
            api_key="sk-test",
            use_max_completion_tokens=True,
            max_output_tokens=32768,
            reasoning_effort="medium",
        )
        body = c._build_request_body(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert body["max_completion_tokens"] == 32768
        assert body["reasoning_effort"] == "medium"

    def test_non_gpt5_models_omit_reasoning_effort(self):
        c = OpenAICompatibleAgentLlmClient(
            api_key="sk-test",
            use_max_completion_tokens=True,
        )
        body = c._build_request_body(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "reasoning_effort" not in body
        assert body["max_completion_tokens"] == 16384


class TestOpenAIGenerateStructured:
    @patch("urllib.request.urlopen")
    def test_sends_to_chat_completions_endpoint(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"ok": true}'))
        captured = []

        def capture(req, timeout=None):
            captured.append(req)
            return mock_urlopen.return_value

        mock_urlopen.side_effect = capture
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        client.generate_structured(
            system_prompt="s", user_payload={}, model="gpt-4o", timeout_seconds=30
        )
        assert "/v1/chat/completions" in captured[0].full_url

    @patch("urllib.request.urlopen")
    def test_system_sent_as_first_message_not_top_level_field(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"ok": true}'))
        bodies = []

        def capture(req, timeout=None):
            bodies.append(json.loads(req.data.decode()))
            return mock_urlopen.return_value

        mock_urlopen.side_effect = capture
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        client.generate_structured(
            system_prompt="Be helpful.",
            user_payload={"q": "test"},
            model="gpt-4o",
            timeout_seconds=30,
        )
        body = bodies[0]
        assert "system" not in body
        assert body["messages"][0] == {"role": "system", "content": "Be helpful."}

    @patch("urllib.request.urlopen")
    def test_uses_bearer_auth_header(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"ok": true}'))
        captured = []

        def capture(req, timeout=None):
            captured.append(req)
            return mock_urlopen.return_value

        mock_urlopen.side_effect = capture
        client = OpenAICompatibleAgentLlmClient(api_key="sk-secret")
        client.generate_structured(
            system_prompt="s", user_payload={}, model="gpt-4o", timeout_seconds=30
        )
        assert captured[0].get_header("Authorization") == "Bearer sk-secret"

    @patch("urllib.request.urlopen")
    def test_extracts_json_from_choices(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"answer": 42}'))
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        result = client.generate_structured(
            system_prompt="s", user_payload={}, model="gpt-4o", timeout_seconds=30
        )
        assert result == {"answer": 42}

    @patch("urllib.request.urlopen")
    def test_extracts_json_wrapped_in_prose(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(
            _text_resp('Here is the result:\n```json\n{"answer": 42}\n```')
        )
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        result = client.generate_structured(
            system_prompt="s", user_payload={}, model="gpt-4o", timeout_seconds=30
        )
        assert result == {"answer": 42}


class TestOpenAIGenerateWithTools:
    @patch("urllib.request.urlopen")
    def test_tool_schema_wrapped_in_function_object(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"r": 1}'))
        bodies = []

        def capture(req, timeout=None):
            bodies.append(json.loads(req.data.decode()))
            return mock_urlopen.return_value

        mock_urlopen.side_effect = capture
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        client.generate_with_tools(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ],
            model="gpt-4o",
            max_tool_calls=0,
            timeout_seconds=30,
        )
        sent_tools = bodies[0]["tools"]
        assert sent_tools[0]["type"] == "function"
        assert sent_tools[0]["function"]["name"] == "search"
        assert "parameters" in sent_tools[0]["function"]
        assert "query" in sent_tools[0]["function"]["parameters"]["properties"]

    @patch("urllib.request.urlopen")
    def test_tool_call_invokes_registry_and_continues(self, mock_urlopen):
        first = _tool_call_resp(
            [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "fed"}'},
                }
            ]
        )
        second = _text_resp('{"result": "done"}')
        responses = iter([first, second])

        def next_resp(req, timeout=None):
            body = next(responses)
            f = MagicMock()
            f.read.return_value = json.dumps(body).encode()
            cm = MagicMock()
            cm.__enter__.return_value = f
            cm.__exit__.return_value = False
            return cm

        mock_urlopen.side_effect = next_resp
        tool_registry = MagicMock()
        tool_registry.invoke.return_value = {
            "is_error": False,
            "content": "search results",
        }
        client = OpenAICompatibleAgentLlmClient(
            api_key="sk-test", tool_registry=tool_registry
        )
        result = client.generate_with_tools(
            system_prompt="sys",
            messages=[{"role": "user", "content": "search something"}],
            tools=[
                {
                    "name": "search",
                    "description": "Search",
                    "parameters": {"type": "object"},
                }
            ],
            model="gpt-4o",
            max_tool_calls=4,
            timeout_seconds=30,
        )
        tool_registry.invoke.assert_called_once_with("search", {"query": "fed"})
        assert result.parsed_output == {"result": "done"}
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search"
        assert result.tool_calls[0].is_error is False

    @patch("urllib.request.urlopen")
    def test_tool_result_sent_as_tool_role_message(self, mock_urlopen):
        first = _tool_call_resp(
            [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "x"}'},
                }
            ]
        )
        second = _text_resp('{"r": 1}')
        responses = iter([first, second])
        bodies = []

        def next_resp(req, timeout=None):
            bodies.append(json.loads(req.data.decode()))
            body = next(responses)
            f = MagicMock()
            f.read.return_value = json.dumps(body).encode()
            cm = MagicMock()
            cm.__enter__.return_value = f
            cm.__exit__.return_value = False
            return cm

        mock_urlopen.side_effect = next_resp
        tool_registry = MagicMock()
        tool_registry.invoke.return_value = {
            "is_error": False,
            "content": "result text",
        }
        client = OpenAICompatibleAgentLlmClient(
            api_key="sk-test", tool_registry=tool_registry
        )
        client.generate_with_tools(
            system_prompt="sys",
            messages=[{"role": "user", "content": "go"}],
            tools=[
                {"name": "search", "description": "S", "parameters": {"type": "object"}}
            ],
            model="gpt-4o",
            max_tool_calls=4,
            timeout_seconds=30,
        )
        second_body_messages = bodies[1]["messages"]
        tool_msg = second_body_messages[-1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_abc"
        assert "untrusted data" in tool_msg["content"].lower()

    @patch("urllib.request.urlopen")
    def test_token_usage_maps_prompt_to_input(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen(_text_resp('{"r": 1}'))
        client = OpenAICompatibleAgentLlmClient(api_key="sk-test")
        result = client.generate_with_tools(
            system_prompt="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model="gpt-4o",
            max_tool_calls=0,
            timeout_seconds=30,
        )
        assert result.token_usage.input_tokens == 100  # from prompt_tokens
        assert result.token_usage.output_tokens == 50  # from completion_tokens
        assert result.token_usage.cache_read_input_tokens == 0
        assert result.token_usage.cache_creation_input_tokens == 0


class TestBuildAgentLlmClient:
    def _settings(
        self, provider: str, key: str = "sk-test", base_url: str | None = None
    ) -> Settings:
        from unittest.mock import MagicMock

        s = MagicMock(spec=Settings)
        s.agent_execution_enabled = True
        s.agent_llm_provider = provider
        s.agent_llm_api_key = key
        s.agent_llm_base_url = base_url
        s.agent_llm_max_output_tokens = 16384
        s.agent_llm_reasoning_effort = None
        return s

    def test_openai_provider_returns_openai_client(self):
        client = build_agent_llm_client(self._settings("openai"))
        assert isinstance(client, OpenAICompatibleAgentLlmClient)
        assert client._use_max_completion_tokens is True

    def test_openai_compatible_provider_returns_openai_client(self):
        client = build_agent_llm_client(self._settings("openai_compatible"))
        assert isinstance(client, OpenAICompatibleAgentLlmClient)
        assert client._use_max_completion_tokens is False

    def test_anthropic_provider_is_rejected(self):
        client = build_agent_llm_client(self._settings("anthropic"))
        assert client is None

    def test_unknown_provider_returns_none(self):
        client = build_agent_llm_client(self._settings("unknown_llm"))
        assert client is None

    def test_disabled_returns_none(self):
        s = MagicMock(spec=Settings)
        s.agent_execution_enabled = False
        assert build_agent_llm_client(s) is None
