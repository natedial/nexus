"""Challenges, rebuttals and concessions must move the outcome of a claim."""

from __future__ import annotations

import pytest

from research_analysis_layer.models import (
    DebateArgument,
    DebateRelation,
    DebateRelationType,
)
from research_analysis_layer.services.debate_ranker import DebateRanker

SESSION = "s"
KEYS = [f"chunk-{i}:assertion-0" for i in range(4)]


def arg(argument_id, turn="proposal", *, cites=2, target=None, text=None, **extra):
    return DebateArgument(
        argument_id=argument_id,
        session_id=SESSION,
        turn_name=turn,
        agent_name=turn,
        argument_text=text or f"text {argument_id}",
        target_claim_id=target,
        cited_assertion_keys=KEYS[:cites],
        **extra,
    )


def rel(kind, source, target, strength=0.8):
    return DebateRelation(
        relation_id=f"{kind}:{source}:{target}",
        session_id=SESSION,
        relation_type=DebateRelationType(kind),
        source_argument_id=source,
        target_argument_id=target,
        strength=strength,
    )


def rank(arguments, relations=()):
    scores, verdicts = DebateRanker().rank_arguments(
        session_id=SESSION, arguments=arguments, relations=list(relations)
    )
    return (
        {s.argument_id: s.final_score for s in scores},
        {v.argument_id: v.verdict_label.value for v in verdicts},
    )


@pytest.mark.parametrize("cites", [1, 2, 4])
def test_grounded_unrebutted_challenge_blocks_acceptance(cites):
    proposal = arg("P", cites=cites, target_instrument="10Y", time_horizon="weeks")
    challenge = arg("C", "challenge", cites=4, target="P")
    _, alone = rank([proposal])
    _, labels = rank([proposal, challenge], [rel("challenges", "C", "P", 0.9)])
    assert alone["P"] == "accepted"
    assert labels["P"] == "contested"
    assert labels["C"] != "accepted"


def test_stronger_challenge_lowers_the_score_more():
    proposal, challenge = arg("P", cites=4), arg("C", "challenge", target="P")
    scores = [
        rank([proposal, challenge], [rel("challenges", "C", "P", s)])[0]["P"]
        for s in (0.0, 0.5, 1.0)
    ]
    assert scores[0] > scores[1] > scores[2]


def test_more_independent_challenges_lower_the_score_more():
    proposal = arg("P", cites=4)
    attacks = [arg(f"C{i}", "challenge", target="P") for i in range(3)]
    links = [rel("challenges", f"C{i}", "P", 0.5) for i in range(3)]
    one = rank([proposal, attacks[0]], links[:1])[0]["P"]
    three = rank([proposal, *attacks], links)[0]["P"]
    assert three < one


def test_grounded_rebuttal_restores_the_claim_and_defeats_the_challenge():
    arguments = [
        arg("P", cites=4),
        arg("C", "challenge", cites=2, target="P"),
        arg("B", "rebuttal", cites=4, target="C"),
    ]
    links = [rel("challenges", "C", "P", 0.9), rel("rebuts", "B", "C", 1.0)]
    _, labels = rank(arguments, links)
    assert labels == {"P": "accepted", "C": "rejected", "B": "accepted"}


def test_rebuttal_aimed_at_the_claim_answers_its_challenges():
    arguments = [
        arg("P", cites=4),
        arg("C", "challenge", cites=2, target="P"),
        arg("B", "rebuttal", cites=4, target="P"),
    ]
    links = [rel("challenges", "C", "P", 0.9), rel("rebuts", "B", "P", 1.0)]
    assert rank(arguments, links)[1]["P"] == "accepted"


@pytest.mark.parametrize("concede_target", ["P", "C"])
def test_conceded_claim_is_rejected_and_the_challenge_sustained(concede_target):
    arguments = [
        arg("P", cites=4),
        arg("C", "challenge", cites=2, target="P"),
        arg("B", "rebuttal", cites=4, target=concede_target),
    ]
    links = [
        rel("challenges", "C", "P", 0.9),
        rel("concedes", "B", concede_target, 1.0),
    ]
    _, labels = rank(arguments, links)
    assert labels["P"] == "rejected"
    assert labels["C"] == "accepted"


def test_only_the_defender_can_concede():
    arguments = [arg("P", cites=4), arg("C", "challenge", target="P")]
    links = [rel("concedes", "C", "P", 1.0)]
    assert rank(arguments, links)[1]["P"] == "accepted"


def test_uncited_challenge_does_not_contest_a_cited_claim():
    arguments = [arg("P", cites=2), arg("C", "challenge", cites=0, target="P")]
    _, labels = rank(arguments, [rel("challenges", "C", "P", 1.0)])
    assert labels["P"] == "accepted"
    assert labels["C"] == "needs_more_evidence"


def test_uncited_claim_is_never_accepted():
    claim = arg(
        "P",
        cites=0,
        target_instrument="10Y",
        time_horizon="2 weeks",
        invalidation_condition="CPI above 0.4",
    )
    rival = arg("Q", cites=0, target_instrument="10Y", time_horizon="2 weeks")
    assert "accepted" not in rank([claim, rival])[1].values()


def test_unrelated_claims_do_not_compete_for_one_slot():
    arguments = [
        arg("T1", cites=4, text="Fed on hold"),
        arg("T2", cites=3, text="Oil supply tightens"),
    ]
    assert rank(arguments)[1] == {"T1": "accepted", "T2": "accepted"}


def test_having_a_weak_rival_does_not_raise_a_score():
    same = dict(target_instrument="10Y", time_horizon="weeks")
    alone = rank([arg("X", cites=1, **same)])[0]["X"]
    contested = rank([arg("X", cites=1, **same), arg("Y", cites=0, **same)])[0]["X"]
    assert contested <= alone


def test_repeating_one_citation_earns_nothing():
    once = arg("P", cites=0)
    many = arg("P", cites=0)
    once.cited_assertion_keys = [KEYS[0]]
    many.cited_assertion_keys = [KEYS[0]] * 4
    assert rank([many])[0]["P"] == rank([once])[0]["P"]


def test_only_a_challenger_can_challenge():
    arguments = [arg("P", cites=4), arg("B", "rebuttal", cites=4, target="P")]
    _, labels = rank(arguments, [rel("challenges", "B", "P", 1.0)])
    assert labels["P"] == "accepted"
