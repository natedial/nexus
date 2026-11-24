"""What each role is shown: whole threads, and dissent all the way to synthesis."""

from __future__ import annotations

from collections import Counter
from unittest.mock import MagicMock

from research_analysis_layer.models import (
    DebateArgument,
    DebateRelation,
    DebateScore,
    DebateSession,
    DebateVerdict,
)
from research_analysis_layer.services.debate_session_builder import DebateSessionBuilder
from research_analysis_layer.services.round_executor import RoundExecutor


def arg(argument_id, turn="proposal", target=None):
    return DebateArgument(
        argument_id=argument_id,
        session_id="s",
        turn_name=turn,
        agent_name=f"agent-for-{turn}",
        argument_text=argument_id,
        target_claim_id=target,
        metadata={"model_used": "secret-model", "prompt_version": "prompt:abc"},
    )


def rel(kind, source, target):
    return DebateRelation(
        relation_id=f"{kind}:{source}",
        session_id="s",
        relation_type=kind,
        source_argument_id=source,
        target_argument_id=target,
    )


def verdict(argument_id, label):
    return DebateVerdict(
        verdict_id=f"v:{argument_id}",
        session_id="s",
        argument_id=argument_id,
        verdict_label=label,
    )


def session(*, verdicts=()):
    proposals = [arg(f"s:proposal:{i}") for i in range(1, 7)]
    challenges = [arg(f"s:challenge:{i}", "challenge", f"s:proposal:{i}") for i in (1, 2, 3)]
    rebuttals = [arg(f"s:rebuttal:{i}", "rebuttal", f"s:challenge:{i}") for i in (1, 2, 3)]
    return DebateSession(
        session_id="s",
        research_id=1,
        document_hash="h",
        analysis_version="v",
        run_id=1,
        arguments=[*proposals, *challenges, *rebuttals],
        relations=[
            *[rel("challenges", f"s:challenge:{i}", f"s:proposal:{i}") for i in (1, 2, 3)],
            *[rel("rebuts", f"s:rebuttal:{i}", f"s:challenge:{i}") for i in (1, 2, 3)],
        ],
        verdicts=list(verdicts),
    )


def executor(cap=8):
    return RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="on",
        max_debate_arguments=cap,
    )


def view(session_, selector, **kwargs):
    context = DebateSessionBuilder().build_round_context(
        session=session_, target_selector=selector, **kwargs
    )
    return context.model_dump(mode="json")


def test_cap_never_shows_a_challenge_without_its_rebuttal():
    capped, truncated = executor()._apply_argument_cap(view(session(), "all"))
    ids = {item["argument_id"] for item in capped["arguments"]}
    assert truncated
    assert len(ids) == 8
    for i in (1, 2, 3):
        assert (f"challenge:{i}" in ids) == (f"rebuttal:{i}" in ids)
    assert Counter(i.split(":")[0] for i in ids)["rebuttal"] >= 2


def test_cap_mixes_challenged_and_unchallenged_claims():
    capped, _ = executor()._apply_argument_cap(view(session(), "all"))
    ids = {item["argument_id"] for item in capped["arguments"]}
    assert ids & {"proposal:1", "proposal:2", "proposal:3"}
    assert ids & {"proposal:4", "proposal:5", "proposal:6"}


def test_cap_keeps_the_whole_context_consistent_and_says_what_was_left_out():
    capped, _ = executor()._apply_argument_cap(view(session(), "all"))
    ids = {item["argument_id"] for item in capped["arguments"]}
    assert set(capped["open_targets"]) <= ids
    for relation in capped["relations"]:
        assert relation["source_argument_id"] in ids
        assert relation["target_argument_id"] in ids
    assert capped["omitted_argument_count"] == 4


def test_one_thread_larger_than_the_cap_keeps_challenge_and_rebuttal_pairs():
    big = session()
    big.arguments = [arg("s:proposal:1")]
    for i in range(1, 7):
        big.arguments.append(arg(f"s:challenge:{i}", "challenge", "s:proposal:1"))
        big.arguments.append(arg(f"s:rebuttal:{i}", "rebuttal", f"s:challenge:{i}"))
    big.relations = []
    capped, _ = executor(cap=5)._apply_argument_cap(view(big, "all"))
    assert [a["argument_id"] for a in capped["arguments"]] == [
        "proposal:1", "challenge:1", "rebuttal:1", "challenge:2", "rebuttal:2",
    ]


def test_synthesizer_view_keeps_contested_and_rejected_arguments_with_verdicts():
    labels = {
        "s:proposal:1": "accepted",
        "s:proposal:2": "contested",
        "s:proposal:3": "needs_more_evidence",
        "s:challenge:1": "rejected",
        "s:challenge:2": "contested",
    }
    context = view(session(verdicts=[verdict(k, v) for k, v in labels.items()]), "adjudicated")
    shown = {v["argument_id"]: v["verdict_label"] for v in context["verdicts"]}
    assert shown == {key.removeprefix("s:"): value for key, value in labels.items()}
    assert set(shown) <= {a["argument_id"] for a in context["arguments"]}


def test_fully_contested_debate_still_reaches_the_synthesizer():
    contested = session(
        verdicts=[verdict("s:proposal:1", "contested"), verdict("s:challenge:1", "contested")]
    )
    context = view(contested, "adjudicated")
    assert context["debate_held"] is True
    assert len(context["arguments"]) >= 2
    assert {v["verdict_label"] for v in context["verdicts"]} == {"contested"}


def test_models_see_short_handles_not_session_ids():
    context = view(session(), "all")
    blob = [a["argument_id"] for a in context["arguments"]]
    blob += [a["target_claim_id"] for a in context["arguments"] if a["target_claim_id"]]
    blob += context["open_targets"]
    for r in context["relations"]:
        blob += [r["source_argument_id"], r["target_argument_id"]]
    assert all(not item.startswith("s:") for item in blob)


def test_blind_view_hides_identity_scores_and_prior_verdicts():
    with_scores = session(verdicts=[verdict("s:proposal:1", "accepted")])
    with_scores.scores = [
        DebateScore(score_id="x", session_id="s", argument_id="s:proposal:1", final_score=0.9)
    ]
    context = view(with_scores, "all", blind=True)
    assert context["scores"] == [] and context["verdicts"] == []
    for argument in context["arguments"]:
        assert "agent_name" not in argument or not argument["agent_name"]
        assert "secret-model" not in str(argument)
        assert "prompt:abc" not in str(argument)


def test_challenged_claim_is_left_out_rather_than_shown_as_unchallenged():
    small = session()
    small.arguments = [
        arg("s:proposal:1"),
        arg("s:challenge:1", "challenge", "s:proposal:1"),
        arg("s:proposal:2"),
        arg("s:challenge:2", "challenge", "s:proposal:2"),
    ]
    small.relations = []
    capped, _ = executor(cap=3)._apply_argument_cap(view(small, "all"))
    assert [a["argument_id"] for a in capped["arguments"]] == ["proposal:1", "challenge:1"]
