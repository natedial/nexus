"""The shipped config and prompts must actually use the integrity controls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_analysis_layer.main import _print_debate_panel
from research_analysis_layer.services.agent_registry import AgentRegistry
from research_analysis_layer.services.model_family import model_family
from research_analysis_layer.services.role_clients import build_provider_clients, describe_panel

DEBATE_AGENTS = ["proposer_thesis", "proposer_positioning", "challenger", "rebuttal",
                 "adjudicator", "adjudicator_independent", "synthesizer"]


@pytest.fixture(scope="module")
def registry():
    return AgentRegistry()


def rounds(registry):
    return {r.name: r for r in registry.get_rounds()}


def test_adjudication_is_a_blind_parallel_panel_from_two_families(registry):
    adjudication = rounds(registry)["adjudication"]
    assert adjudication.blind and adjudication.type == "parallel"
    families = {model_family(registry.get_agent(name).model) for name in adjudication.agents}
    assert len(families) == 2 and None not in families


def test_independent_judge_has_its_own_provider(registry):
    assert registry.get_agent("adjudicator_independent").provider == "anthropic"
    assert registry.get_agent("adjudicator").provider is None


def test_judges_run_the_same_prompt(registry):
    assert registry.load_prompt("adjudicator") == registry.load_prompt("adjudicator_independent")


def test_synthesis_sees_the_whole_adjudicated_debate(registry):
    assert rounds(registry)["synthesis"].target_selector == "adjudicated"


@pytest.mark.parametrize("name", DEBATE_AGENTS)
def test_prompt_loads_with_includes_resolved(registry, name):
    prompt = registry.load_prompt(name)
    assert prompt and "{{include" not in prompt


@pytest.mark.parametrize("name", ["challenger", "rebuttal"])
def test_dissenting_roles_are_not_told_to_drop_doubt(registry, name):
    assert "Do not emit" not in registry.load_prompt(name)


@pytest.mark.parametrize("name", DEBATE_AGENTS[:6])
def test_every_debating_role_may_abstain(registry, name):
    assert "abstain" in registry.load_prompt(name).lower()


@pytest.mark.parametrize("name", DEBATE_AGENTS[:4])
def test_authoring_roles_are_told_how_to_link_arguments(registry, name):
    assert "local_id" in registry.load_prompt(name)


def test_judges_are_not_asked_for_scores_the_orchestrator_ignores(registry):
    prompt = registry.load_prompt("adjudicator")
    assert "final_score" not in prompt and "pairwise_wins" not in prompt


def settings(mode="on"):
    return SimpleNamespace(analyst_debate_mode=mode, analyst_debate_judge_model=None)


def test_provider_client_is_built_when_a_key_exists(registry, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert set(build_provider_clients(settings(), registry)) == {"anthropic"}


def test_missing_key_leaves_the_provider_out(registry, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert build_provider_clients(settings(), registry) == {}


def test_no_second_provider_is_touched_while_debate_is_off(registry, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert build_provider_clients(settings("off"), registry) == {}


def test_panel_description_reports_independence(registry):
    ready = describe_panel(registry, available_providers={"anthropic"})
    assert ready.independent is True
    missing = describe_panel(registry, available_providers=set())
    assert missing.independent is False
    assert missing.unavailable == ["adjudicator_independent"]


def test_judge_override_into_the_same_family_is_reported(registry):
    panel = describe_panel(registry, available_providers={"anthropic"}, judge_model="claude-opus-5-5")
    assert panel.independent is False


@pytest.mark.parametrize("key,expected", [("test-key", "independent=yes"), ("", "independent=no")])
def test_doctor_prints_panel_independence(monkeypatch, capsys, key, expected):
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    _print_debate_panel(settings())
    assert expected in capsys.readouterr().out


def test_doctor_says_nothing_about_the_panel_when_debate_is_off(capsys):
    _print_debate_panel(settings("off"))
    assert capsys.readouterr().out == ""
