import os
import pytest
from research_analysis_layer.config import Settings


def _base_env(monkeypatch, **overrides):
    base = {
        "PARSED_DB_URL": "http://x",
        "PARSED_DB_KEY": "k",
        "STATE_DB_PATH": "/nonexistent/state.db",
    }
    for k in (
        "ANALYST_DEBATE_MODE",
        "ANALYST_DEBATE_JUDGE_MODEL",
        "ANALYST_MAX_DEBATE_ARGUMENTS",
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in {**base, **overrides}.items():
        monkeypatch.setenv(k, v)


def test_debate_mode_defaults_to_off(monkeypatch):
    _base_env(monkeypatch)
    s = Settings.from_env()
    assert s.analyst_debate_mode == "off"
    assert s.analyst_debate_judge_model is None
    assert s.analyst_max_debate_arguments == 8


def test_debate_mode_reads_env(monkeypatch):
    _base_env(
        monkeypatch,
        ANALYST_DEBATE_MODE="shadow",
        ANALYST_DEBATE_JUDGE_MODEL="gpt-5-mini",
        ANALYST_MAX_DEBATE_ARGUMENTS="4",
    )
    s = Settings.from_env()
    assert s.analyst_debate_mode == "shadow"
    assert s.analyst_debate_judge_model == "gpt-5-mini"
    assert s.analyst_max_debate_arguments == 4


def test_validate_rejects_unknown_mode(monkeypatch):
    _base_env(monkeypatch, ANALYST_DEBATE_MODE="bogus")
    s = Settings.from_env()
    errors = s.validate()
    assert any("analyst_debate_mode" in e for e in errors)


def test_validate_rejects_nonpositive_max_arguments(monkeypatch):
    _base_env(monkeypatch, ANALYST_MAX_DEBATE_ARGUMENTS="0")
    s = Settings.from_env()
    errors = s.validate()
    assert any("analyst_max_debate_arguments" in e for e in errors)


def test_validate_rejects_anthropic_provider(monkeypatch):
    _base_env(
        monkeypatch,
        AGENT_EXECUTION_ENABLED="true",
        AGENT_LLM_PROVIDER="anthropic",
        AGENT_LLM_API_KEY="sk-test",
    )
    s = Settings.from_env()
    errors = s.validate()
    assert any("anthropic is no longer supported" in e for e in errors)


def test_validate_codex_does_not_require_api_key(monkeypatch, tmp_path):
    fake_bin = tmp_path / "codex"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)
    _base_env(
        monkeypatch,
        AGENT_EXECUTION_ENABLED="true",
        AGENT_LLM_PROVIDER="codex",
        AGENT_LLM_CODEX_BIN=str(fake_bin),
    )
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    s = Settings.from_env()
    errors = s.validate()
    assert not any("api key" in e.lower() for e in errors)
    assert s.agent_execution_enabled is True


def test_validate_codex_requires_binary(monkeypatch):
    _base_env(
        monkeypatch,
        AGENT_EXECUTION_ENABLED="true",
        AGENT_LLM_PROVIDER="codex",
        AGENT_LLM_CODEX_BIN="/no/such/codex-binary",
    )
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    s = Settings.from_env()
    errors = s.validate()
    assert any("codex CLI not found" in e for e in errors)


def test_codex_provider_enables_agents_without_explicit_flag(monkeypatch, tmp_path):
    fake_bin = tmp_path / "codex"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)
    _base_env(
        monkeypatch,
        AGENT_LLM_PROVIDER="codex",
        AGENT_LLM_CODEX_BIN=str(fake_bin),
    )
    monkeypatch.delenv("AGENT_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    s = Settings.from_env()
    assert s.agent_execution_enabled is True


def test_codex_model_override_from_env(monkeypatch, tmp_path):
    fake_bin = tmp_path / "codex"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)
    _base_env(
        monkeypatch,
        AGENT_LLM_PROVIDER="codex",
        AGENT_LLM_CODEX_BIN=str(fake_bin),
        AGENT_LLM_CODEX_MODEL="gpt-5.6-sol",
    )
    s = Settings.from_env()
    assert s.agent_llm_codex_model == "gpt-5.6-sol"
