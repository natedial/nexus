"""Combine hard floors, the structural ranking and a blind panel into verdicts.

No single layer can accept a claim alone. Evidence and concession floors are
absolute. One judge cannot overrule the structural result; judges from two model
families that agree can. Any other split is kept as ``contested`` rather than
averaged away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from research_analysis_layer.models.debate_models import (
    DebateArgument,
    DebateRelation,
    DebateRelationType,
    DebateRoundOutput,
    DebateScore,
    DebateVerdict,
    DebateVerdictLabel as Label,
)

_ACCEPT = {Label.ACCEPTED, Label.SYNTHESIZED}
_MAX_REASON_CHARS = 160


@dataclass(frozen=True)
class JudgeBallot:
    """One judge's independent rulings."""

    judge: str
    family: str | None
    votes: dict[str, tuple[str, str]] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    synthesizes: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_round_output(
        cls, output: DebateRoundOutput, *, family: str | None
    ) -> JudgeBallot:
        votes: dict[str, tuple[str, str]] = {}
        for verdict in output.verdicts:
            votes.setdefault(
                verdict.argument_id, (verdict.verdict_label.value, verdict.reason)
            )
        return cls(
            judge=output.turn.agent_name,
            family=family,
            votes=votes,
            scores={
                score.argument_id: score.llm_judge_score
                for score in output.scores
                if score.llm_judge_score is not None
            },
            synthesizes={
                verdict.argument_id: verdict.synthesizes_from
                for verdict in output.verdicts
                if verdict.synthesizes_from
            },
        )


def resolve_verdicts(
    *,
    arguments: list[DebateArgument],
    relations: list[DebateRelation],
    ranked_scores: list[DebateScore],
    ranked_verdicts: list[DebateVerdict],
    ballots: list[JudgeBallot],
    untested: bool = False,
) -> tuple[list[DebateScore], list[DebateVerdict]]:
    """Return final scores and verdicts for every argument in the session.

    ``untested`` means the challenger failed, so surviving is not evidence.
    """
    score_by_id = {score.argument_id: score for score in ranked_scores}
    ranked_by_id = {verdict.argument_id: verdict for verdict in ranked_verdicts}
    scores: list[DebateScore] = []
    verdicts: list[DebateVerdict] = []
    for argument in arguments:
        argument_id = argument.argument_id
        score, ranked = score_by_id[argument_id], ranked_by_id[argument_id]
        judged = [
            ballot.scores[argument_id]
            for ballot in ballots
            if argument_id in ballot.scores
        ]
        scores.append(
            score.model_copy(
                update={
                    "llm_judge_score": sum(judged) / len(judged) if judged else None
                }
            )
        )
        votes = [
            (ballot, Label(ballot.votes[argument_id][0]))
            for ballot in ballots
            if argument_id in ballot.votes
            and ballot.votes[argument_id][0] != Label.ABSTAINED.value
        ]
        label, basis = _decide(score, ranked, votes)
        if untested and label in _ACCEPT:
            label = Label.NEEDS_MORE_EVIDENCE
            basis = "Challenger failed, so it was never challenged."
        layers = [f"structure={ranked.verdict_label.value}"]
        for ballot in ballots:
            if argument_id in ballot.votes:
                vote, why = ballot.votes[argument_id]
                detail = f" ({why[:_MAX_REASON_CHARS]})" if why else ""
                layers.append(f"{ballot.judge}={vote}{detail}")
        synthesizes = [
            item
            for ballot in ballots
            for item in ballot.synthesizes.get(argument_id, [])
        ]
        verdicts.append(
            ranked.model_copy(
                update={
                    "verdict_label": label,
                    "reason": f"{basis} [{'; '.join(layers)}]",
                    "synthesizes_from": list(dict.fromkeys(synthesizes)),
                }
            )
        )
    return scores, _separate_claims_from_attacks(arguments, relations, verdicts)


def _decide(
    score: DebateScore,
    ranked: DebateVerdict,
    votes: list[tuple[JudgeBallot, Label]],
) -> tuple[Label, str]:
    structure = ranked.verdict_label
    features = score.deterministic_features
    labels = {label for _, label in votes}
    if features.has_accepted_contradiction:
        return Label.REJECTED, "Conceded by its defender."
    if features.evidence_count == 0 and structure != Label.ACCEPTED:
        if labels == {Label.REJECTED}:
            return Label.REJECTED, "No verifiable citation, and judges rejected it."
        return Label.NEEDS_MORE_EVIDENCE, "No verifiable citation."
    if not votes:
        if structure == Label.ACCEPTED:
            return Label.NEEDS_MORE_EVIDENCE, "No judge ruled on it."
        return structure, ranked.reason

    families = {ballot.family for ballot, _ in votes if ballot.family}
    independent = len(families) >= 2
    if labels <= _ACCEPT:
        if structure in _ACCEPT or independent:
            agreed = labels.pop() if len(labels) == 1 else Label.ACCEPTED
            return agreed, "Judges accepted it."
        return Label.CONTESTED, "Judges accepted it against the structural result."
    if labels == {Label.REJECTED}:
        if independent or structure in {Label.REJECTED, Label.NEEDS_MORE_EVIDENCE}:
            return Label.REJECTED, "Judges rejected it."
        return Label.CONTESTED, "Judges rejected it against the structural result."
    if len(labels) == 1:
        return labels.pop(), "Judges withheld acceptance."
    return Label.CONTESTED, "Judges disagreed."


def _separate_claims_from_attacks(
    arguments: list[DebateArgument],
    relations: list[DebateRelation],
    verdicts: list[DebateVerdict],
) -> list[DebateVerdict]:
    turn_by_id = {item.argument_id: item.turn_name for item in arguments}
    accepted = {v.argument_id for v in verdicts if v.verdict_label in _ACCEPT}
    clashing: set[str] = set()
    for relation in relations:
        pair = {relation.source_argument_id, relation.target_argument_id}
        if (
            relation.relation_type == DebateRelationType.CHALLENGES
            and turn_by_id.get(relation.source_argument_id) == "challenge"
            and pair <= accepted
        ):
            clashing |= pair
    return [
        verdict.model_copy(
            update={
                "verdict_label": Label.CONTESTED,
                "reason": f"Claim and its challenge were both accepted. {verdict.reason}",
            }
        )
        if verdict.argument_id in clashing
        else verdict
        for verdict in verdicts
    ]


def build_open_disputes(
    *,
    session_id: str,
    arguments: list[DebateArgument],
    relations: list[DebateRelation],
    verdicts: list[DebateVerdict],
) -> list[dict]:
    """Claims that did not settle, with the challenges still standing against them.

    Written into the analysis by the orchestrator, so dissent does not depend on
    the synthesizer choosing to mention it.
    """
    by_id = {item.argument_id: item for item in arguments}
    verdict_by_id = {verdict.argument_id: verdict for verdict in verdicts}

    def entry(argument: DebateArgument) -> dict:
        verdict = verdict_by_id[argument.argument_id]
        return {
            "id": argument.argument_id.removeprefix(f"{session_id}:"),
            "verdict": verdict.verdict_label.value,
            "reason": verdict.reason,
            "citations": [
                *argument.cited_chunk_keys,
                *argument.cited_evidence_keys,
                *argument.cited_assertion_keys,
            ],
        }

    disputes: list[dict] = []
    for claim in arguments:
        if claim.turn_name != "proposal" or claim.argument_id not in verdict_by_id:
            continue
        standing = [
            by_id[relation.source_argument_id]
            for relation in relations
            if relation.relation_type == DebateRelationType.CHALLENGES
            and relation.target_argument_id == claim.argument_id
            and relation.source_argument_id in verdict_by_id
            and verdict_by_id[relation.source_argument_id].verdict_label
            in {*_ACCEPT, Label.CONTESTED}
        ]
        unsettled = verdict_by_id[claim.argument_id].verdict_label in {
            Label.CONTESTED,
            Label.NEEDS_MORE_EVIDENCE,
        }
        if not unsettled and not standing:
            continue
        disputes.append(
            {
                **entry(claim),
                "claim": claim.argument_text,
                "challenges": [
                    {**entry(item), "text": item.argument_text} for item in standing
                ],
            }
        )
    return disputes
