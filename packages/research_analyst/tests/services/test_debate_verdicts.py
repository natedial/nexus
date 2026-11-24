"""A verdict needs evidence, structure and judges to line up; splits stay visible."""

from __future__ import annotations

import pytest

from research_analysis_layer.models import DebateArgument, DebateRelation, DebateScore, DebateVerdict
from research_analysis_layer.models.debate_models import DeterministicScoreFeature
from research_analysis_layer.services.debate_verdicts import JudgeBallot, resolve_verdicts
from research_analysis_layer.services.model_family import model_family


def decide(structure, *votes, evidence=2, conceded=False):
    """votes: (family, label)."""
    argument = DebateArgument(
        argument_id="P", session_id="s", turn_name="proposal", agent_name="p", argument_text="t"
    )
    score = DebateScore(
        score_id="x", session_id="s", argument_id="P", final_score=0.6,
        deterministic_features=DeterministicScoreFeature(
            evidence_count=evidence, has_accepted_contradiction=conceded),
    )
    ranked = DebateVerdict(
        verdict_id="s:verdict:P", session_id="s", argument_id="P",
        verdict_label=structure, reason="structural",
    )
    ballots = [
        JudgeBallot(judge=f"judge{i}", family=family, votes={"P": (label, "because")}, scores={"P": 0.4})
        for i, (family, label) in enumerate(votes)
    ]
    scores, verdicts = resolve_verdicts(
        arguments=[argument], relations=[], ranked_scores=[score],
        ranked_verdicts=[ranked], ballots=ballots,
    )
    return verdicts[0], scores[0]


G, C = "openai-gpt", "anthropic-claude"


@pytest.mark.parametrize("structure,votes,expected", [
    ("accepted", [(G, "accepted")], "accepted"),
    ("accepted", [(G, "accepted"), (C, "accepted")], "accepted"),
    # one judge, or one family twice, cannot overrule structure
    ("contested", [(G, "accepted")], "contested"),
    ("contested", [(G, "accepted"), (G, "accepted")], "contested"),
    ("accepted", [(G, "rejected")], "contested"),
    # two families agreeing can
    ("contested", [(G, "accepted"), (C, "accepted")], "accepted"),
    ("accepted", [(G, "rejected"), (C, "rejected")], "rejected"),
    # judges split
    ("accepted", [(G, "accepted"), (C, "rejected")], "contested"),
    ("accepted", [(G, "accepted"), (C, "needs_more_evidence")], "contested"),
    # abstention is not a vote
    ("accepted", [(G, "accepted"), (C, "abstained")], "accepted"),
    ("contested", [(G, "accepted"), (C, "abstained")], "contested"),
    ("accepted", [(G, "abstained"), (C, "abstained")], "needs_more_evidence"),
    ("accepted", [], "needs_more_evidence"),
    ("rejected", [], "rejected"),
    # an unknown family never counts as independent
    ("contested", [(None, "accepted"), (G, "accepted")], "contested"),
])
def test_verdict_matrix(structure, votes, expected):
    assert decide(structure, *votes)[0].verdict_label.value == expected


def test_no_panel_can_accept_a_claim_without_verifiable_citations():
    verdict, _ = decide("needs_more_evidence", (G, "accepted"), (C, "accepted"), evidence=0)
    assert verdict.verdict_label.value == "needs_more_evidence"


def test_no_panel_can_accept_a_conceded_claim():
    verdict, _ = decide("rejected", (G, "accepted"), (C, "accepted"), conceded=True)
    assert verdict.verdict_label.value == "rejected"


def test_reason_shows_how_each_layer_ruled():
    verdict, _ = decide("accepted", (G, "accepted"), (C, "rejected"))
    for part in ("structure=accepted", "judge0=accepted", "judge1=rejected"):
        assert part in verdict.reason


def test_judges_do_not_replace_the_structural_score():
    _, score = decide("accepted", (G, "accepted"))
    assert score.final_score == 0.6
    assert score.llm_judge_score == 0.4
    assert score.deterministic_features.evidence_count == 2


def test_a_claim_and_the_attack_on_it_cannot_both_be_accepted():
    def item(i, turn):
        return DebateArgument(argument_id=i, session_id="s", turn_name=turn, agent_name=turn, argument_text=i)

    def score(i):
        return DebateScore(score_id=i, session_id="s", argument_id=i,
                           deterministic_features=DeterministicScoreFeature(evidence_count=2))

    def ranked(i, label):
        return DebateVerdict(verdict_id=i, session_id="s", argument_id=i, verdict_label=label)

    ballots = [JudgeBallot(judge=f, family=f, votes={"P": ("accepted", ""), "C": ("accepted", "")}, scores={})
               for f in (G, C)]
    _, verdicts = resolve_verdicts(
        arguments=[item("P", "proposal"), item("C", "challenge")],
        relations=[DebateRelation(relation_id="r", session_id="s", relation_type="challenges",
                                  source_argument_id="C", target_argument_id="P")],
        ranked_scores=[score("P"), score("C")],
        ranked_verdicts=[ranked("P", "contested"), ranked("C", "contested")], ballots=ballots,
    )
    assert {v.verdict_label.value for v in verdicts} == {"contested"}


@pytest.mark.parametrize("name,family", [
    ("gpt-5-mini", G), ("gpt-5.6-terra", G), ("claude-sonnet-5-5", C), ("mystery-1", None), ("", None),
])
def test_model_family(name, family):
    assert model_family(name) == family
