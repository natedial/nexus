"""Whole debates through the real executor with scripted models."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.services.agent_llm_client import AgentCallResult
from research_analysis_layer.services.agent_registry import AgentConfig
from research_analysis_layer.services.round_executor import AgentSpec, RoundConfig, RoundExecutor

SYNTHESIS = {
    "thesis": "t", "contrarian_view": "c", "recommended_positioning": "r", "confidence": 0.5,
    "open_disputes": [{"claim": "forged by the model"}],
}
PROPOSAL = {"arguments": [
    {"argument_text": "Rates stay high.", "cited_assertion_keys": ["chunk-1:assertion-1", "chunk-2:assertion-1"]}]}
CHALLENGE = {"arguments": [
    {"argument_text": "Growth is rolling over.", "target_claim_id": "proposal:1",
     "cited_assertion_keys": ["chunk-2:assertion-1"], "metadata": {"challenge_mode": "weaken"}}],
    "relations": [{"relation_type": "challenges", "target_argument_id": "proposal:1", "strength": 0.9}]}


def ballot(label, *ids):
    return {"verdicts": [{"argument_id": i, "verdict_label": label, "reason": "because"} for i in ids]}


class Client:
    """Replies by agent name (the registry returns the name as the prompt)."""

    def __init__(self, replies, model=None, supports_tools=True):
        self.replies, self.model, self.supports_tools = replies, model, supports_tools
        self.seen: dict[str, dict] = {}

    def generate_with_tools(self, *, system_prompt, messages, tools, model, **_):
        self.seen[system_prompt] = {"messages": messages, "tools": tools, "blob": json.dumps(messages)}
        reply = self.replies[system_prompt]
        if isinstance(reply, Exception):
            raise reply
        return AgentCallResult(raw_text="", parsed_output=json.loads(json.dumps(reply)),
                               model_used=self.model or model, stop_reason="stop")


class Builder:
    def build(self, **_):
        return {"doc": "payload"}

    def to_messages(self, data):
        return [{"role": "user", "content": json.dumps(data, default=str)}]


def round_(name, agents, **kw):
    kw.setdefault("type", "parallel")
    kw.setdefault("output_schema", "DebateRoundOutput")
    kw.setdefault("writes_forum_state", True)
    kw.setdefault("receives_forum_state", True)
    return RoundConfig(name=name, agents=agents, receives=["input"], **kw)


ROUNDS = [
    round_("proposal", ["proposer_thesis"], receives_forum_state=False),
    round_("challenge", ["challenger"], target_selector="challenge_targets"),
    round_("rebuttal", ["rebuttal"], target_selector="rebuttal_targets"),
    round_("adjudication", ["adjudicator", "adjudicator_independent"], target_selector="all", blind=True),
    round_("synthesis", ["synthesizer"], type="sequential", output_schema="DocumentAnalysis",
           writes_forum_state=False, target_selector="adjudicated"),
]


def spec(name, *, provider=None, tools=()):
    config = AgentConfig(name=name, prompt_path="", model="gpt-5-mini", fallback_model="gpt-5-mini",
                         timeout_seconds=5, retry_count=1, priority=1, table_name=name,
                         tools=list(tools), provider=provider)
    return AgentSpec(name=name, config=config, tools=[], max_tool_calls=0, timeout_seconds=5,
                     retry_count=1, temperature=0.2,
                     output_schema="DocumentAnalysis" if name == "synthesizer" else "DebateRoundOutput")


SPECS = {name: spec(name, provider="anthropic" if name == "adjudicator_independent" else None)
         for r in ROUNDS for name in r.agents}


def run(tmp_path, *, provider_clients="default", specs=SPECS, default_model=None, **replies):
    script = {
        "proposer_thesis": PROPOSAL, "challenger": CHALLENGE, "rebuttal": {"abstain": True, "abstain_reason": "no answer"},
        "adjudicator": ballot("contested", "proposal:1", "challenge:1"),
        "adjudicator_independent": ballot("contested", "proposal:1", "challenge:1"),
        "synthesizer": SYNTHESIS, **replies,
    }
    main, other = Client(script, default_model), Client(script, "claude-sonnet-5-5")
    registry = MagicMock()
    registry.load_prompt.side_effect = lambda name: name
    store = AnalysisStore(tmp_path / "analysis.db")
    executor = RoundExecutor(
        registry=registry, llm_client=main, input_builder=Builder(), analysis_store=store, debate_mode="on",
        provider_clients={"anthropic": other} if provider_clients == "default" else provider_clients,
    )
    document = SimpleNamespace(
        research_id=7, document_hash="h", file_id=None, themes=[], spans=[],
        document=SimpleNamespace(source_date="2026-04-14", parsed_data={}),
    )
    assertions = [SimpleNamespace(chunk_order=i, assertion_order=1) for i in (1, 2)]
    analysis = executor.run(document=document, chunks=[], evidence_units=[], assertions=assertions,
                            run_id=1, analysis_version="v", rounds=ROUNDS, agent_specs=specs)
    return SimpleNamespace(analysis=analysis, session=store.load_debate_session("debate:7:h:v:1"),
                           main=main, other=other, executor=executor, store=store)


def labels(result):
    return {v["argument_id"].split("debate:7:h:v:1:")[-1]: v["verdict_label"] for v in result.session["verdicts"]}


def test_contested_debate_reaches_the_synthesizer_and_the_output(tmp_path):
    result = run(tmp_path)
    assert labels(result) == {"proposal:1": "contested", "challenge:1": "contested"}
    blob = result.main.seen["synthesizer"]["blob"]
    assert "Rates stay high." in blob and "Growth is rolling over." in blob
    dispute = result.analysis.open_disputes[0]
    assert dispute["claim"] == "Rates stay high."
    assert dispute["challenges"][0]["text"] == "Growth is rolling over."
    assert len(result.analysis.open_disputes) == 1
    assert result.analysis.payload_json["open_disputes"] == result.analysis.open_disputes


def test_judges_are_blind_to_identity_and_to_each_other(tmp_path):
    result = run(tmp_path)
    for seen in (result.main.seen["adjudicator"], result.other.seen["adjudicator_independent"]):
        assert "proposer_thesis" not in seen["blob"]
        assert "because" not in seen["blob"]
        assert "final_score" not in seen["blob"]


def test_independent_judge_runs_on_its_own_provider(tmp_path):
    result = run(tmp_path)
    assert set(result.other.seen) == {"adjudicator_independent"}
    assert "adjudicator_independent" not in result.main.seen


def test_judge_disagreement_is_kept_as_contested(tmp_path):
    result = run(tmp_path, challenger={"abstain": True, "abstain_reason": "sound"},
                 adjudicator=ballot("accepted", "proposal:1"),
                 adjudicator_independent=ballot("rejected", "proposal:1"))
    assert labels(result) == {"proposal:1": "contested"}


def test_missing_independent_judge_is_visible_and_weakens_the_panel(tmp_path):
    result = run(tmp_path, provider_clients={}, adjudicator=ballot("accepted", "proposal:1", "challenge:1"))
    assert labels(result)["proposal:1"] == "contested"
    turns = {t["agent_name"]: t["turn_summary"] for t in result.session["turns"]}
    assert "failed" in turns["adjudicator_independent"].lower()


def test_same_family_twice_is_not_independent(tmp_path):
    same = Client({"adjudicator_independent": ballot("accepted", "proposal:1", "challenge:1")}, "gpt-5")
    result = run(tmp_path, provider_clients={"anthropic": same}, adjudicator=ballot("accepted", "proposal:1"))
    assert labels(result)["proposal:1"] == "contested"


def test_failed_panel_never_yields_acceptance(tmp_path):
    result = run(tmp_path, challenger={"abstain": True, "abstain_reason": "sound"},
                 adjudicator=RuntimeError("down"), adjudicator_independent=RuntimeError("down"))
    assert labels(result) == {"proposal:1": "needs_more_evidence"}


def test_accepted_when_structure_and_both_families_agree(tmp_path):
    result = run(tmp_path, challenger={"abstain": True, "abstain_reason": "sound"},
                 adjudicator=ballot("accepted", "proposal:1"),
                 adjudicator_independent=ballot("accepted", "proposal:1"))
    assert labels(result) == {"proposal:1": "accepted"}
    assert result.analysis.open_disputes == []


def test_fabricated_citations_cannot_be_accepted(tmp_path):
    fake = {"arguments": [{"argument_text": "x", "cited_assertion_keys": [f"chunk-9{i}:assertion-{i}" for i in range(4)]}]}
    result = run(tmp_path, proposer_thesis=fake, challenger={"abstain": True},
                 adjudicator=ballot("accepted", "proposal:1"),
                 adjudicator_independent=ballot("accepted", "proposal:1"))
    assert labels(result) == {"proposal:1": "needs_more_evidence"}


def test_everyone_abstaining_completes_without_arguments(tmp_path):
    none = {"abstain": True, "abstain_reason": "nothing to say"}
    result = run(tmp_path, proposer_thesis=none, challenger=none, rebuttal=none,
                 adjudicator=none, adjudicator_independent=none)
    assert result.session["session"]["status"] == "completed"
    assert '\\"debate_held\\": true' in json.dumps(result.main.seen["synthesizer"]["blob"])[:4000] or \
        '"debate_held": true' in result.main.seen["synthesizer"]["messages"][0]["content"]


def test_agent_configured_with_tools_is_told_when_it_has_none(tmp_path):
    specs = {**SPECS, "challenger": spec("challenger", tools=["research_search"])}
    result = run(tmp_path, specs=specs)
    assert "Tools are unavailable" in result.main.seen["challenger"]["blob"]
    assert "Tools are unavailable" not in result.main.seen["rebuttal"]["blob"]


def test_blind_rounds_must_be_parallel():
    with pytest.raises(ValueError, match="blind"):
        RoundConfig(name="adjudication", type="sequential", agents=["a"], receives=[], blind=True)


def test_crash_mid_debate_marks_the_session_abandoned(tmp_path, monkeypatch):
    monkeypatch.setattr(RoundExecutor, "_supplement_adjudication_outputs",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        run(tmp_path)
    store = AnalysisStore(tmp_path / "analysis.db")
    assert store.load_debate_session("debate:7:h:v:1")["session"]["status"] == "abandoned"
