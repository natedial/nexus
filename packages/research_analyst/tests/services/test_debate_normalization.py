"""Agents propose content; the orchestrator owns identity, links and provenance."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research_analysis_layer.models import DebateSession
from research_analysis_layer.services.agent_llm_client import AgentCallResult, ToolCallTrace
from research_analysis_layer.services.round_executor import RoundConfig, RoundExecutor, RoundResult

ALLOWED = {"chunk-1", "chunk-1:assertion-0", "chunk-2:assertion-0", "chunk-2:evidence-1"}


def make_executor():
    registry = MagicMock()
    registry.load_prompt.return_value = "the prompt"
    return RoundExecutor(
        registry=registry, llm_client=MagicMock(), input_builder=MagicMock(), debate_mode="on"
    )


def make_session():
    return DebateSession(
        session_id="s", research_id=1, document_hash="h", analysis_version="v", run_id=1
    )


def collect(session, round_name, *outputs, executor=None, allowed=ALLOWED, order=2):
    """outputs: (agent_name, payload) or (agent_name, payload, ref_keys)."""
    executor = executor or make_executor()
    results = []
    for item in outputs:
        agent_name, payload, ref_keys = (*item, [])[:3]
        traces = [ToolCallTrace("research_search", {}, "", 1, False, list(ref_keys))] if ref_keys else []
        results.append(
            AgentCallResult(
                raw_text="", parsed_output=payload, tool_calls=traces,
                model_used=f"model-for-{agent_name}", agent_name=agent_name, attempt_count=2,
            )
        )
    round_config = RoundConfig(
        name=round_name, type="parallel", agents=[o[0] for o in outputs],
        receives=["input"], output_schema="DebateRoundOutput", writes_forum_state=True,
    )
    rounds = executor._collect_debate_round_outputs(
        round_config=round_config,
        result=RoundResult(round_name, results, 1, 0, 0),
        session=session, turn_order=order, allowed_ref_keys=allowed,
    )
    executor._persist_debate_round_outputs(session=session, round_outputs=rounds)
    return rounds


def claim(text="claim", cites=("chunk-1:assertion-0",), **extra):
    return {"argument_text": text, "cited_assertion_keys": list(cites), **extra}


def propose(session, count=2):
    return collect(
        session, "proposal",
        ("proposer", {"arguments": [claim(f"claim {i}") for i in range(count)]}), order=1,
    )


def test_model_supplied_ids_cannot_collide_or_overwrite():
    session = make_session()
    collect(
        session, "proposal",
        ("proposer_a", {"arguments": [claim("a", argument_id="arg-1", session_id="other")]}),
        ("proposer_b", {"arguments": [claim("b", argument_id="arg-1", agent_name="proposer_a")]}),
        order=1,
    )
    assert len({a.argument_id for a in session.arguments}) == 2
    assert {a.session_id for a in session.arguments} == {"s"}
    assert {a.agent_name for a in session.arguments} == {"proposer_a", "proposer_b"}


def test_parallel_agents_do_not_share_relation_ids():
    session = make_session()
    propose(session)
    payload = lambda target: {"arguments": [claim(target_claim_id=target)],
                              "relations": [{"relation_type": "challenges", "target_argument_id": target}]}
    collect(session, "challenge", ("c1", payload("proposal:1")), ("c2", payload("proposal:2")))
    ids = [r.relation_id for r in session.relations]
    assert len(ids) == 2 == len(set(ids))


def test_short_handles_resolve_to_session_arguments():
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {
        "target_argument_ids": ["proposal:2"],
        "arguments": [claim(target_claim_id="proposal:2")],
        "relations": [{"relation_type": "challenges", "target_argument_id": "proposal:2"}],
    }))
    challenge = session.arguments[-1]
    assert challenge.target_claim_id == "s:proposal:2"
    assert session.relations[0].target_argument_id == "s:proposal:2"
    assert session.relations[0].source_argument_id == challenge.argument_id


def test_omitted_source_is_matched_by_target_not_defaulted_to_the_first_argument():
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {
        "arguments": [claim("x", target_claim_id="proposal:1"), claim("y", target_claim_id="proposal:2")],
        "relations": [{"relation_type": "challenges", "target_argument_id": "proposal:1"},
                      {"relation_type": "challenges", "target_argument_id": "proposal:2"}],
    }))
    links = {(r.source_argument_id, r.target_argument_id) for r in session.relations}
    assert links == {("s:challenge:1", "s:proposal:1"), ("s:challenge:2", "s:proposal:2")}


def test_local_ids_link_arguments_created_in_the_same_response():
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {
        "arguments": [claim("x", local_id="a1", target_claim_id="proposal:1"),
                      claim("y", local_id="a2", target_claim_id="proposal:1")],
        "relations": [{"relation_type": "challenges", "source_argument_id": "a2", "target_argument_id": "proposal:1"}],
    }))
    assert any(r.source_argument_id == "s:challenge:2" for r in session.relations)


def test_unresolvable_links_are_dropped_and_reported():
    session = make_session()
    propose(session)
    rounds = collect(session, "challenge", ("c", {
        "arguments": [claim("x", target_claim_id="proposal:1"), claim("y", target_claim_id="proposal:1")],
        "relations": [{"relation_type": "challenges", "source_argument_id": "made-up", "target_argument_id": "proposal:1"},
                      {"relation_type": "challenges", "source_argument_id": "challenge:1", "target_argument_id": "nope"}],
    }))
    known = {a.argument_id for a in session.arguments}
    assert all(r.source_argument_id in known and r.target_argument_id in known for r in session.relations)
    assert "relation" in (rounds[0].error or "")


def test_targeted_challenge_without_a_relation_still_counts_as_a_challenge():
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {"arguments": [claim(target_claim_id="proposal:1")]}))
    assert [(r.relation_type.value, r.target_argument_id) for r in session.relations] == [
        ("challenges", "s:proposal:1")
    ]


@pytest.mark.parametrize("stance,kind", [("concede", "concedes"), ("narrow", "rebuts"), ("defend", "rebuts")])
def test_rebuttal_stance_supplies_a_missing_relation(stance, kind):
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {"arguments": [claim(target_claim_id="proposal:1")]}))
    collect(session, "rebuttal", ("r", {"arguments": [
        claim("z", target_claim_id="challenge:1", metadata={"rebuttal_stance": stance})]}), order=3)
    assert session.relations[-1].relation_type.value == kind


@pytest.mark.parametrize("bad", [
    {"relation_type": "undercuts", "target_argument_id": "proposal:1"},
    {"relation_type": "challenges", "source_argument_id": None, "target_argument_id": None},
    {"relation_type": "challenges", "target_argument_id": "proposal:1", "strength": "very"},
    "not an object",
])
def test_one_malformed_relation_does_not_lose_the_turn(bad):
    session = make_session()
    propose(session)
    rounds = collect(session, "challenge", ("c", {
        "arguments": [claim(target_claim_id="proposal:1")], "relations": [bad]}))
    assert len(rounds[0].arguments) == 1


@pytest.mark.parametrize("bad", ["text", {"cited_assertion_keys": []}, claim(uncertainty=7), claim(thesis_type="vibes")])
def test_one_malformed_argument_does_not_lose_the_others(bad):
    session = make_session()
    rounds = collect(session, "proposal", ("p", {"arguments": [bad, claim("good")]}), order=1)
    assert [a.argument_text for a in rounds[0].arguments][-1] == "good"
    assert rounds[0].error or len(rounds[0].arguments) == 2


@pytest.mark.parametrize("field", ["arguments", "relations", "verdicts", "scores", "target_argument_ids"])
def test_wrongly_typed_sections_do_not_raise(field):
    collect(make_session(), "proposal", ("p", {"arguments": [claim()], field: "oops"}), order=1)


def test_unknown_citations_are_removed_and_recorded():
    session = make_session()
    collect(session, "proposal", ("p", {"arguments": [claim(
        cites=["chunk-1:assertion-0", "chunk-999:assertion-9"], cited_chunk_keys=["chunk-1", "chunk-77"])]}), order=1)
    argument = session.arguments[0]
    assert argument.cited_assertion_keys == ["chunk-1:assertion-0"]
    assert argument.cited_chunk_keys == ["chunk-1"]
    assert set(argument.metadata.dropped_citations) == {"chunk-999:assertion-9", "chunk-77"}


def test_keys_retrieved_by_a_tool_are_citable_and_stay_citable_later():
    session, executor = make_session(), make_executor()
    propose(session)
    collect(session, "challenge", ("c", {"arguments": [
        claim(cites=[], cited_chunk_keys=["corpus-9"], target_claim_id="proposal:1")]}, ["corpus-9"]), executor=executor)
    assert session.arguments[-1].cited_chunk_keys == ["corpus-9"]
    collect(session, "rebuttal", ("r", {"arguments": [
        claim(cites=[], cited_chunk_keys=["corpus-9", "corpus-10"], target_claim_id="challenge:1")]}), executor=executor, order=3)
    assert session.arguments[-1].cited_chunk_keys == ["corpus-9"]


def test_stance_and_provenance_are_kept_on_every_argument():
    session = make_session()
    propose(session)
    collect(session, "challenge", ("c", {"arguments": [claim(
        target_claim_id="proposal:1",
        metadata={"challenge_mode": "weaken", "model_used": "spoofed", "prompt_version": "spoofed"})]}))
    metadata = session.arguments[-1].metadata
    assert metadata.challenge_mode.value == "weaken"
    assert metadata.model_used == "model-for-c"
    assert metadata.prompt_version.startswith("prompt:") and "spoofed" not in metadata.prompt_version
    assert metadata.attempt_count == 2


def test_abstention_is_recorded_and_is_not_an_error():
    session = make_session()
    propose(session)
    rounds = collect(session, "challenge", ("c", {"abstain": True, "abstain_reason": "claims are well supported"}))
    assert rounds[0].error is None
    assert rounds[0].turn.turn_summary == "Abstained: claims are well supported"


def test_allowed_keys_come_from_the_document_the_agents_were_given():
    keys = RoundExecutor._allowed_argument_ref_keys(
        document=SimpleNamespace(), chunks=[SimpleNamespace(chunk_order=1)],
        evidence_units=[], assertions=[SimpleNamespace(chunk_order=1, assertion_order=0)],
    )
    assert {"chunk-1", "chunk-1:assertion-0"} <= keys
