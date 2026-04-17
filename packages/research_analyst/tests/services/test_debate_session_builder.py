from research_analysis_layer.models import (
    DebateArgument,
    DebateRelation,
    DebateRelationType,
    DebateScore,
    DebateSession,
    DebateVerdict,
    DebateVerdictLabel,
    ThesisType,
)
from research_analysis_layer.services.debate_session_builder import DebateSessionBuilder


def _session() -> DebateSession:
    proposal = DebateArgument(
        argument_id="arg-1",
        session_id="sess-1",
        turn_name="proposal",
        agent_name="proposer_thesis",
        thesis_type=ThesisType.THESIS,
        argument_text="Rates stay higher for longer.",
        cited_assertion_keys=["chunk-1:assertion-1"],
    )
    challenge = DebateArgument(
        argument_id="arg-2",
        session_id="sess-1",
        turn_name="challenge",
        agent_name="challenger",
        thesis_type=ThesisType.CONTRARIAN,
        argument_text="Growth rollover weakens the higher-for-longer thesis.",
        target_claim_id="arg-1",
        cited_assertion_keys=["chunk-2:assertion-1"],
    )
    accepted_score = DebateScore(
        score_id="score-1",
        session_id="sess-1",
        argument_id="arg-1",
        final_score=0.72,
    )
    rejected_score = DebateScore(
        score_id="score-2",
        session_id="sess-1",
        argument_id="arg-2",
        final_score=0.31,
    )
    accepted_verdict = DebateVerdict(
        verdict_id="verdict-1",
        session_id="sess-1",
        argument_id="arg-1",
        verdict_label=DebateVerdictLabel.ACCEPTED,
        reason="Grounded in multiple assertions.",
    )
    rejected_verdict = DebateVerdict(
        verdict_id="verdict-2",
        session_id="sess-1",
        argument_id="arg-2",
        verdict_label=DebateVerdictLabel.REJECTED,
        reason="Attack undercut by weaker evidence.",
    )
    relation = DebateRelation(
        relation_id="rel-1",
        session_id="sess-1",
        relation_type=DebateRelationType.CHALLENGES,
        source_argument_id="arg-2",
        target_argument_id="arg-1",
        strength=0.7,
    )
    return DebateSession(
        session_id="sess-1",
        research_id=1,
        document_hash="hash-1",
        analysis_version="v1",
        run_id=7,
        arguments=[proposal, challenge],
        relations=[relation],
        scores=[accepted_score, rejected_score],
        verdicts=[accepted_verdict, rejected_verdict],
    )


def test_build_round_context_filters_to_challenged_subset():
    builder = DebateSessionBuilder()
    context = builder.build_round_context(
        session=_session(),
        target_selector="rebuttal_targets",
    )

    assert {argument.argument_id for argument in context.arguments} == {"arg-1", "arg-2"}
    assert context.open_targets == ["arg-1"]
    assert len(context.relations) == 1


def test_build_round_context_filters_to_accepted_only():
    builder = DebateSessionBuilder()
    context = builder.build_round_context(
        session=_session(),
        target_selector="accepted_only",
    )

    assert [argument.argument_id for argument in context.arguments] == ["arg-1"]
    assert [score.argument_id for score in context.scores] == ["arg-1"]
    assert [verdict.argument_id for verdict in context.verdicts] == ["arg-1"]
