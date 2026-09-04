"""Tests for the Codex CLI agent LLM client."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_analysis_layer.services.agent_llm_client import (
    CodexCliAgentLlmClient,
    _flatten_message_content,
    build_agent_llm_client,
)
from research_analysis_layer.config import Settings


def _settings(*, provider: str = "codex", key: str | None = None, enabled: bool = True):
    s = MagicMock(spec=Settings)
    s.agent_execution_enabled = enabled
    s.agent_llm_provider = provider
    s.agent_llm_api_key = key
    s.agent_llm_base_url = None
    s.agent_llm_codex_bin = "/usr/bin/true"
    s.agent_llm_codex_model = None
    s.agent_llm_max_output_tokens = 16384
    s.agent_llm_reasoning_effort = None
    return s


def _fake_run(message: str, returncode: int = 0, stdout: str = "", stderr: str = ""):
    def fake_run(cmd, **kwargs):
        out_path = Path(cmd[cmd.index("--output-last-message") + 1])
        out_path.write_text(message, encoding="utf-8")
        return subprocess.CompletedProcess(
            cmd, returncode, stdout=stdout, stderr=stderr
        )

    return fake_run


class TestFlattenMessageContent:
    def test_string(self):
        assert _flatten_message_content("hello") == "hello"

    def test_anthropic_blocks(self):
        content = [{"type": "text", "text": '{"ok": true}'}]
        assert _flatten_message_content(content) == '{"ok": true}'

    def test_none(self):
        assert _flatten_message_content(None) == ""


class TestCodexCliClient:
    def test_generate_with_tools_uses_codex_exec_flags(self):
        client = CodexCliAgentLlmClient(binary="/opt/homebrew/bin/codex")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            out_path = Path(cmd[cmd.index("--output-last-message") + 1])
            out_path.write_text('{"thesis": "ok"}', encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=fake_run,
        ):
            result = client.generate_with_tools(
                system_prompt="Be a synthesizer.",
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": '{"doc": 1}'}],
                    }
                ],
                tools=[],
                model="gpt-5",
                max_tool_calls=0,
                timeout_seconds=45,
            )

        cmd = captured["cmd"]
        assert cmd[0] == "/opt/homebrew/bin/codex"
        assert cmd[1] == "exec"
        assert "--ephemeral" in cmd
        assert "--ignore-user-config" in cmd
        assert "--skip-git-repo-check" in cmd
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"
        assert cmd[cmd.index("-m") + 1] == "gpt-5.6-terra"
        assert cmd[-1] == "-"
        assert "--output-schema" in cmd
        assert "--output-last-message" in cmd
        prompt = captured["kwargs"]["input"]
        assert "Be a synthesizer." in prompt
        assert '{"doc": 1}' in prompt
        assert "JSON-only" in prompt
        assert captured["kwargs"]["timeout"] == 45
        env = captured["kwargs"]["env"]
        assert "OPENAI_API_KEY" not in env
        assert "AGENT_LLM_API_KEY" not in env
        assert result.parsed_output == {"thesis": "ok"}
        assert result.model_used == "gpt-5.6-terra"
        assert result.stop_reason == "stop"
        assert result.tool_calls == []

    def test_generate_structured_parses_fenced_json(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=_fake_run('Here you go:\n```json\n{"answer": 7}\n```\n'),
        ):
            result = client.generate_structured(
                system_prompt="sys",
                user_payload={"q": "x"},
                model="gpt-5-mini",
                timeout_seconds=30,
            )
        assert result == {"answer": 7}

    def test_ignores_tools_and_still_answers(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=_fake_run('{"ok": true}'),
        ):
            result = client.generate_with_tools(
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "research_search", "parameters": {}}],
                model="gpt-5",
                max_tool_calls=2,
                timeout_seconds=30,
            )
        assert result.parsed_output == {"ok": True}
        assert result.tool_calls == []

    def test_maps_mini_to_luna(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            out_path = Path(cmd[cmd.index("--output-last-message") + 1])
            out_path.write_text('{"ok": true}', encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=fake_run,
        ):
            result = client.generate_with_tools(
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                model="gpt-5-mini",
                max_tool_calls=0,
                timeout_seconds=10,
            )
        assert captured["cmd"][captured["cmd"].index("-m") + 1] == "gpt-5.6-luna"
        assert result.model_used == "gpt-5.6-luna"

    def test_model_override_wins(self):
        client = CodexCliAgentLlmClient(
            binary="/usr/bin/true",
            model_override="gpt-5.6-sol",
        )
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            out_path = Path(cmd[cmd.index("--output-last-message") + 1])
            out_path.write_text('{"ok": true}', encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=fake_run,
        ):
            client.generate_with_tools(
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                model="gpt-5",
                max_tool_calls=0,
                timeout_seconds=10,
            )
        assert captured["cmd"][captured["cmd"].index("-m") + 1] == "gpt-5.6-sol"

    def test_surfaces_chatgpt_unsupported_model_error(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        stderr = (
            '{"prompt": "huge dump"}\n'
            'ERROR: {"type":"error","status":400,"error":{'
            '"type":"invalid_request_error",'
            '"message":"The \'gpt-5\' model is not supported when using Codex with a ChatGPT account."}}'
        )
        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=_fake_run("not json", returncode=1, stderr=stderr),
        ):
            with pytest.raises(RuntimeError, match="not supported when using Codex"):
                client.generate_with_tools(
                    system_prompt="sys",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    model="gpt-5",
                    max_tool_calls=0,
                    timeout_seconds=10,
                )

    def test_nonzero_exit_with_empty_output_raises(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=_fake_run("", returncode=1, stderr="login required"),
        ):
            with pytest.raises(RuntimeError, match="exited 1"):
                client.generate_with_tools(
                    system_prompt="sys",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    model="gpt-5",
                    max_tool_calls=0,
                    timeout_seconds=10,
                )

    def test_nonzero_exit_with_last_message_still_parses(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")
        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=_fake_run('{"ok": true}', returncode=1, stderr="warn"),
        ):
            result = client.generate_with_tools(
                system_prompt="sys",
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                model="gpt-5",
                max_tool_calls=0,
                timeout_seconds=10,
            )
        assert result.parsed_output == {"ok": True}

    def test_timeout_raises(self):
        client = CodexCliAgentLlmClient(binary="/usr/bin/true")

        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=kwargs.get("cmd") or args[:1], timeout=1)

        with patch(
            "research_analysis_layer.services.agent_llm_client.subprocess.run",
            side_effect=boom,
        ):
            with pytest.raises(TimeoutError, match="timed out"):
                client.generate_with_tools(
                    system_prompt="sys",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    model="gpt-5",
                    max_tool_calls=0,
                    timeout_seconds=1,
                )

    def test_child_env_strips_api_keys(self):
        env = {
            "OPENAI_API_KEY": "sk-secret",
            "AGENT_LLM_API_KEY": "sk-agent",
            "PATH": "/usr/bin",
        }
        with patch.dict("os.environ", env, clear=True):
            child = CodexCliAgentLlmClient._child_env()
        assert "OPENAI_API_KEY" not in child
        assert "AGENT_LLM_API_KEY" not in child
        assert child["PATH"] == "/usr/bin"


class TestBuildCodexClient:
    def test_codex_provider_does_not_need_api_key(self):
        with patch(
            "research_analysis_layer.services.agent_llm_client.resolve_codex_bin",
            return_value="/opt/homebrew/bin/codex",
        ):
            client = build_agent_llm_client(_settings(key=None))
        assert isinstance(client, CodexCliAgentLlmClient)
        assert client.binary == "/opt/homebrew/bin/codex"

    def test_codex_provider_returns_none_without_binary(self):
        with patch(
            "research_analysis_layer.services.agent_llm_client.resolve_codex_bin",
            return_value=None,
        ):
            assert build_agent_llm_client(_settings(key=None)) is None

    def test_openai_still_requires_api_key(self):
        assert build_agent_llm_client(_settings(provider="openai", key=None)) is None
