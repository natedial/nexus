"""Tool turns must not consume transport attempts or hide token spend."""

from __future__ import annotations

import json

from research_analysis_layer.services.agent_llm_client import (
    CodexCliAgentLlmClient,
    OpenAICompatibleAgentLlmClient,
)


class _Registry:
    def __init__(self):
        self.calls = 0

    def invoke(self, name, input_data):
        self.calls += 1
        return {
            "is_error": False,
            "content": [{"chunk_id": f"corpus-{self.calls}", "text_excerpt": "x"}],
        }


class _ScriptedClient(OpenAICompatibleAgentLlmClient):
    """Asks for one tool per turn for ``tool_turns`` turns, then answers."""

    def __init__(self, *, tool_turns: int, **kwargs):
        super().__init__(api_key="test", **kwargs)
        self.tool_turns = tool_turns
        self.bodies: list[dict] = []

    def _make_request(self, request, timeout_seconds):
        body = json.loads(request.data)
        self.bodies.append(body)
        usage = {"prompt_tokens": 100, "completion_tokens": 10}
        wants_tool = (
            len(self.bodies) <= self.tool_turns and body.get("tool_choice") != "none"
        )
        if wants_tool:
            call = {
                "id": f"call-{len(self.bodies)}",
                "function": {"name": "research_search", "arguments": "{}"},
            }
            return {
                "usage": usage,
                "choices": [
                    {"finish_reason": "tool_calls", "message": {"tool_calls": [call]}}
                ],
            }
        return {
            "usage": usage,
            "choices": [
                {"finish_reason": "stop", "message": {"content": '{"ok": true}'}}
            ],
        }


def _run(client, *, max_tool_calls=4):
    return client.generate_with_tools(
        system_prompt="",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"name": "research_search", "parameters": {}}],
        model="m",
        max_tool_calls=max_tool_calls,
    )


def test_full_sequential_tool_budget_still_produces_an_answer():
    client = _ScriptedClient(tool_turns=4, tool_registry=_Registry())
    result = _run(client, max_tool_calls=4)
    assert result.parsed_output == {"ok": True}
    assert len(result.tool_calls) == 4


def test_model_that_never_stops_calling_tools_is_forced_to_answer():
    registry = _Registry()
    client = _ScriptedClient(tool_turns=99, tool_registry=registry)
    result = _run(client, max_tool_calls=2)
    assert registry.calls == 2
    assert client.bodies[-1]["tool_choice"] == "none"
    assert result.parsed_output == {"ok": True}


def test_token_usage_accumulates_over_every_turn():
    client = _ScriptedClient(tool_turns=3, tool_registry=_Registry())
    result = _run(client)
    assert result.token_usage.input_tokens == 400
    assert result.token_usage.output_tokens == 40


def test_tool_trace_records_retrieved_reference_keys():
    client = _ScriptedClient(tool_turns=2, tool_registry=_Registry())
    result = _run(client)
    assert [trace.ref_keys for trace in result.tool_calls] == [
        ["corpus-1"],
        ["corpus-2"],
    ]


def test_codex_client_declares_that_it_cannot_use_tools():
    assert CodexCliAgentLlmClient.supports_tools is False
    assert OpenAICompatibleAgentLlmClient.supports_tools is True
