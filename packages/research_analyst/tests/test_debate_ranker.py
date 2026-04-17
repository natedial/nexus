from research_analysis_layer.models import DebateArgument, ThesisType
from research_analysis_layer.services.debate_ranker import DebateRanker


def _argument(
    argument_id: str,
    *,
    text: str,
    target_claim_id: str | None = None,
    assertions: list[str] | None = None,
    chunks: list[str] | None = None,
    instrument: str | None = None,
    time_horizon: str | None = None,
) -> DebateArgument:
    return DebateArgument(
        argument_id=argument_id,
        session_id="sess-1",
        turn_name="proposal",
        agent_name="proposer_thesis",
        thesis_type=ThesisType.POSITIONING if instrument else ThesisType.THESIS,
        argument_text=text,
        target_claim_id=target_claim_id,
        cited_assertion_keys=assertions or [],
        cited_chunk_keys=chunks or [],
        target_instrument=instrument,
        time_horizon=time_horizon,
    )


def test_ranker_marks_duplicate_argument_not_novel():
    ranker = DebateRanker()
    arguments = [
        _argument(
            "arg-1",
            text="Long 10Y UST over the next weeks.",
            assertions=["chunk-1:assertion-1"],
            chunks=["chunk-1"],
            instrument="10Y UST",
            time_horizon="weeks",
        ),
        _argument(
            "arg-2",
            text="Long 10Y UST over the next weeks.",
            assertions=["chunk-1:assertion-1"],
            chunks=["chunk-1"],
            instrument="10Y UST",
            time_horizon="weeks",
        ),
    ]

    scores, verdicts = ranker.rank_arguments(
        session_id="sess-1",
        arguments=arguments,
        relations=[],
    )

    score_by_id = {score.argument_id: score for score in scores}
    verdict_by_id = {verdict.argument_id: verdict for verdict in verdicts}
    assert score_by_id["arg-2"].deterministic_features.is_novel is False
    assert verdict_by_id["arg-1"].verdict_label.value == "accepted"
    assert verdict_by_id["arg-2"].verdict_label.value in {"rejected", "contested"}


def test_ranker_marks_near_tie_as_contested():
    ranker = DebateRanker(tie_threshold=0.10)
    arguments = [
        _argument(
            "arg-1",
            text="Rates stay restrictive for months.",
            assertions=["chunk-1:assertion-1"],
            chunks=["chunk-1", "chunk-2"],
            time_horizon="months",
        ),
        _argument(
            "arg-2",
            text="Rates stay restrictive over the coming months.",
            assertions=["chunk-3:assertion-1"],
            chunks=["chunk-3", "chunk-4"],
            time_horizon="months",
        ),
    ]

    scores, verdicts = ranker.rank_arguments(
        session_id="sess-2",
        arguments=arguments,
        relations=[],
    )

    assert len(scores) == 2
    assert {verdict.verdict_label.value for verdict in verdicts} == {"contested"}
