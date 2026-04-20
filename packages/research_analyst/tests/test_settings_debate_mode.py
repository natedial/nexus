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
