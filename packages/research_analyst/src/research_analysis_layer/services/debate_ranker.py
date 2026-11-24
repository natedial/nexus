"""Deterministic scoring helpers for debate arguments.

A proposal, the challenges against it and the rebuttals of those challenges form
one thread. Only proposals compete for a slot. A challenge is judged by whether
it stands against its target, never as a free-standing claim, so a claim and the
attack on it cannot both be accepted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Callable

from research_analysis_layer.models import (
    DebateArgument,
    DebateRelation,
    DebateRelationType,
    DebateScore,
    DebateVerdict,
    DebateVerdictLabel,
    DeterministicScoreFeature,
)

PairwiseJudge = Callable[[DebateArgument, DebateArgument], str]


# An unanswered attack at or above this force keeps a claim from being accepted.
CONTEST_THRESHOLD = 0.25
ACCEPT_THRESHOLD = 0.35
_MAX_ATTACK_DISCOUNT = 0.6
_CONCEDED_DISCOUNT = 0.7
_PAIRWISE_LOSS_DISCOUNT = 0.3


@dataclass
class ThreadState:
    """How challenges, rebuttals and concessions resolve against each argument."""

    # claim_id -> {challenge_id: residual force after rebuttal}
    attacks: dict[str, dict[str, float]] = field(default_factory=dict)
    # challenge_id -> best rebuttal force against it
    rebutted: dict[str, float] = field(default_factory=dict)
    # rebuttal_id -> challenge_ids it answers
    answers: dict[str, set[str]] = field(default_factory=dict)
    conceded_claims: set[str] = field(default_factory=set)
    conceding_rebuttals: set[str] = field(default_factory=set)

    def attack_force(self, claim_id: str) -> float:
        survival = 1.0
        for residual in self.attacks.get(claim_id, {}).values():
            survival *= 1.0 - residual
        return 1.0 - survival


@dataclass
class DebateRanker:
    """Rank debate arguments with deterministic features plus optional pairwise input."""

    pre_rank_limit: int = 4
    pairwise_limit: int = 6
    tie_threshold: float = 0.03

    def rank_arguments(
        self,
        *,
        session_id: str,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
        judge: PairwiseJudge | None = None,
    ) -> tuple[list[DebateScore], list[DebateVerdict]]:
        if not arguments:
            return [], []

        scores = {
            argument.argument_id: DebateScore(
                score_id=f"{session_id}:score:{argument.argument_id}",
                session_id=session_id,
                argument_id=argument.argument_id,
                deterministic_features=self.extract_features(
                    argument=argument,
                    arguments=arguments,
                    relations=relations,
                ),
            )
            for argument in arguments
        }

        quality = {
            argument_id: self._deterministic_total(score.deterministic_features)
            for argument_id, score in scores.items()
        }
        state = self._resolve_threads(arguments, relations, scores, quality)

        for cluster in self._cluster_arguments(arguments).values():
            ranked = self._pre_rank(cluster, scores)
            if len(ranked) > 1:
                self._run_pairwise(scores, ranked, judge=judge)

        for argument_id, score in scores.items():
            # Losing to a rival costs score; having a weak rival never adds any.
            final = quality[argument_id] * (
                1.0 - _PAIRWISE_LOSS_DISCOUNT * self._pairwise_loss_rate(score)
            )
            final *= 1.0 - _MAX_ATTACK_DISCOUNT * state.attack_force(argument_id)
            final *= 1.0 - state.rebutted.get(argument_id, 0.0)
            score.deterministic_features.has_accepted_contradiction = (
                argument_id in state.conceded_claims
            )
            if argument_id in state.conceded_claims:
                final *= 1.0 - _CONCEDED_DISCOUNT
            score.final_score = max(0.0, min(1.0, final))

        verdicts = self.generate_verdicts(
            session_id=session_id,
            arguments=arguments,
            relations=relations,
            scores=list(scores.values()),
            state=state,
        )
        return list(scores.values()), verdicts

    def _resolve_threads(
        self,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
        scores: dict[str, DebateScore],
        quality: dict[str, float],
    ) -> ThreadState:
        """Work out which attacks stand. Roles are enforced by turn, not by claim."""
        turn_by_id = {item.argument_id: item.turn_name for item in arguments}

        def force(relation: DebateRelation) -> float:
            source = relation.source_argument_id
            if scores[source].deterministic_features.evidence_count == 0:
                return 0.0
            return relation.strength * quality[source]

        usable = [
            relation
            for relation in relations
            if relation.source_argument_id in turn_by_id
            and relation.target_argument_id in turn_by_id
            and relation.source_argument_id != relation.target_argument_id
        ]
        challenges: dict[str, dict[str, float]] = defaultdict(dict)
        claims_by_challenge: dict[str, set[str]] = defaultdict(set)
        for relation in usable:
            if (
                relation.relation_type != DebateRelationType.CHALLENGES
                or turn_by_id[relation.source_argument_id] != "challenge"
            ):
                continue
            by_challenge = challenges[relation.target_argument_id]
            source = relation.source_argument_id
            by_challenge[source] = max(by_challenge.get(source, 0.0), force(relation))
            claims_by_challenge[source].add(relation.target_argument_id)

        state = ThreadState()
        for relation in usable:
            source, target = relation.source_argument_id, relation.target_argument_id
            if turn_by_id[source] != "rebuttal":
                continue
            # Defenders may name the attack or the claim under attack.
            answered = {target} if target in claims_by_challenge else set(
                challenges.get(target, {})
            )
            if relation.relation_type == DebateRelationType.REBUTS:
                state.answers.setdefault(source, set()).update(answered)
                for challenge_id in answered:
                    state.rebutted[challenge_id] = max(
                        state.rebutted.get(challenge_id, 0.0), force(relation)
                    )
            elif relation.relation_type == DebateRelationType.CONCEDES:
                state.conceding_rebuttals.add(source)
                state.conceded_claims.update(
                    claims_by_challenge.get(target) or {target}
                )

        for claim_id, by_challenge in challenges.items():
            state.attacks[claim_id] = {
                challenge_id: attack * (1.0 - state.rebutted.get(challenge_id, 0.0))
                for challenge_id, attack in by_challenge.items()
            }
        return state

    def extract_features(
        self,
        *,
        argument: DebateArgument,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
    ) -> DeterministicScoreFeature:
        cited_refs = set(argument.cited_chunk_keys)
        cited_refs.update(argument.cited_evidence_keys)
        cited_refs.update(argument.cited_assertion_keys)
        unique_chunks = {
            ref.split(":")[0] for ref in cited_refs if isinstance(ref, str) and ref
        }
        evidence_count = len(cited_refs)
        evidence_diversity = (
            min(1.0, len(unique_chunks) / max(1, evidence_count))
            if evidence_count
            else 0.0
        )
        assertion_alignment = min(
            1.0,
            len(set(argument.cited_assertion_keys))
            / max(1, len(set(argument.cited_chunk_keys))),
        )

        has_contradiction = any(
            relation.relation_type == DebateRelationType.CHALLENGES
            and relation.target_argument_id == argument.argument_id
            for relation in relations
        )
        has_accepted_contradiction = any(
            relation.relation_type == DebateRelationType.CONCEDES
            and relation.target_argument_id == argument.argument_id
            for relation in relations
        )

        normalized_text = self._normalize_text(argument.argument_text)
        is_novel = not any(
            other.argument_id != argument.argument_id
            and self._normalize_text(other.argument_text) == normalized_text
            for other in arguments
        ) and not any(
            relation.relation_type == DebateRelationType.DUPLICATES
            and (
                relation.source_argument_id == argument.argument_id
                or relation.target_argument_id == argument.argument_id
            )
            for relation in relations
        )

        return DeterministicScoreFeature(
            evidence_count=evidence_count,
            evidence_diversity=evidence_diversity,
            assertion_alignment=assertion_alignment,
            has_contradiction=has_contradiction,
            has_accepted_contradiction=has_accepted_contradiction,
            time_horizon_specificity=self._time_horizon_specificity(argument.time_horizon),
            conditional_clarity=1.0
            if argument.invalidation_condition or argument.qualifier_text
            else 0.0,
            is_novel=is_novel,
            is_actionable=bool(
                argument.target_instrument
                or argument.invalidation_condition
                or argument.thesis_type.value == "positioning"
            ),
        )

    def generate_verdicts(
        self,
        *,
        session_id: str,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
        scores: list[DebateScore],
        state: ThreadState | None = None,
    ) -> list[DebateVerdict]:
        state = state or ThreadState()
        score_by_id = {score.argument_id: score for score in scores}
        duplicates = self._duplicate_ids(arguments, relations, score_by_id)
        outcomes: dict[str, tuple[DebateVerdictLabel, str]] = {}

        for cluster in self._cluster_arguments(arguments).values():
            outcomes.update(
                self._judge_proposals(cluster, score_by_id, duplicates, state)
            )
        for argument in arguments:
            if argument.argument_id in outcomes:
                continue
            if argument.argument_id in duplicates:
                outcomes[argument.argument_id] = (
                    DebateVerdictLabel.REJECTED,
                    "Duplicate of a stronger argument.",
                )
            elif argument.turn_name == "rebuttal":
                outcomes[argument.argument_id] = self._judge_rebuttal(
                    argument, score_by_id, state
                )
            else:
                outcomes[argument.argument_id] = self._judge_challenge(
                    argument, score_by_id, state
                )

        return [
            DebateVerdict(
                verdict_id=f"{session_id}:verdict:{argument.argument_id}",
                session_id=session_id,
                argument_id=argument.argument_id,
                verdict_label=outcomes[argument.argument_id][0],
                reason=outcomes[argument.argument_id][1],
            )
            for argument in arguments
        ]

    def _judge_proposals(
        self,
        cluster: list[DebateArgument],
        score_by_id: dict[str, DebateScore],
        duplicates: set[str],
        state: ThreadState,
    ) -> dict[str, tuple[DebateVerdictLabel, str]]:
        outcomes: dict[str, tuple[DebateVerdictLabel, str]] = {}
        standing: list[DebateArgument] = []
        for argument in cluster:
            if argument.argument_id in duplicates:
                outcomes[argument.argument_id] = (
                    DebateVerdictLabel.REJECTED,
                    "Duplicate of a stronger argument.",
                )
            elif argument.argument_id in state.conceded_claims:
                outcomes[argument.argument_id] = (
                    DebateVerdictLabel.REJECTED,
                    "Conceded by its defender.",
                )
            else:
                standing.append(argument)
        if not standing:
            return outcomes

        standing.sort(
            key=lambda item: self._order_key(score_by_id[item.argument_id]),
            reverse=True,
        )
        top_score = score_by_id[standing[0].argument_id].final_score
        tied = [
            argument
            for argument in standing
            if abs(score_by_id[argument.argument_id].final_score - top_score)
            <= self.tie_threshold
        ]
        unresolved_tie = len(tied) > 1 and not self._break_tie(score_by_id, tied)
        for argument in standing:
            argument_id = argument.argument_id
            features = score_by_id[argument_id].deterministic_features
            if unresolved_tie and argument in tied and features.evidence_count:
                outcome = (
                    DebateVerdictLabel.CONTESTED,
                    "Near-tie after deterministic tie-breaks.",
                )
            elif argument is not standing[0]:
                outcome = (
                    DebateVerdictLabel.REJECTED,
                    "Lower-ranked within its competing cluster.",
                )
            elif features.evidence_count == 0:
                outcome = (
                    DebateVerdictLabel.NEEDS_MORE_EVIDENCE,
                    "No verifiable citation.",
                )
            elif state.attack_force(argument_id) >= CONTEST_THRESHOLD:
                outcome = (
                    DebateVerdictLabel.CONTESTED,
                    "A grounded challenge stands unanswered.",
                )
            elif top_score < ACCEPT_THRESHOLD:
                outcome = (
                    DebateVerdictLabel.NEEDS_MORE_EVIDENCE,
                    "Top argument remains weakly grounded.",
                )
            else:
                outcome = (
                    DebateVerdictLabel.ACCEPTED,
                    "Best-supported argument in its cluster.",
                )
            outcomes[argument_id] = outcome
        return outcomes

    @staticmethod
    def _judge_challenge(
        argument: DebateArgument,
        score_by_id: dict[str, DebateScore],
        state: ThreadState,
    ) -> tuple[DebateVerdictLabel, str]:
        argument_id = argument.argument_id
        if score_by_id[argument_id].deterministic_features.evidence_count == 0:
            return DebateVerdictLabel.NEEDS_MORE_EVIDENCE, "No verifiable citation."
        targets = {
            claim_id: attacks[argument_id]
            for claim_id, attacks in state.attacks.items()
            if argument_id in attacks
        }
        if not targets:
            return (
                DebateVerdictLabel.NEEDS_MORE_EVIDENCE,
                "Challenge is not linked to a claim.",
            )
        if state.conceded_claims & set(targets):
            return DebateVerdictLabel.ACCEPTED, "Sustained: the defender conceded."
        if max(targets.values()) >= CONTEST_THRESHOLD:
            return DebateVerdictLabel.CONTESTED, "Challenge stands unanswered."
        if state.rebutted.get(argument_id, 0.0) > 0:
            return DebateVerdictLabel.REJECTED, "Answered by a grounded rebuttal."
        return DebateVerdictLabel.NEEDS_MORE_EVIDENCE, "Challenge has little force."

    @staticmethod
    def _judge_rebuttal(
        argument: DebateArgument,
        score_by_id: dict[str, DebateScore],
        state: ThreadState,
    ) -> tuple[DebateVerdictLabel, str]:
        argument_id = argument.argument_id
        if argument_id in state.conceding_rebuttals:
            return DebateVerdictLabel.ACCEPTED, "Concession recorded."
        if score_by_id[argument_id].deterministic_features.evidence_count == 0:
            return DebateVerdictLabel.NEEDS_MORE_EVIDENCE, "No verifiable citation."
        answered = state.answers.get(argument_id, set())
        residuals = [
            residual
            for attacks in state.attacks.values()
            for challenge_id, residual in attacks.items()
            if challenge_id in answered
        ]
        if not residuals:
            return (
                DebateVerdictLabel.NEEDS_MORE_EVIDENCE,
                "Rebuttal is not linked to a challenge.",
            )
        if max(residuals) >= CONTEST_THRESHOLD:
            return DebateVerdictLabel.CONTESTED, "Challenge still stands."
        return DebateVerdictLabel.ACCEPTED, "Answers the challenge."

    def _duplicate_ids(
        self,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
        score_by_id: dict[str, DebateScore],
    ) -> set[str]:
        duplicates = {
            relation.source_argument_id
            for relation in relations
            if relation.relation_type == DebateRelationType.DUPLICATES
        }
        by_text: dict[tuple[str, str], list[DebateArgument]] = defaultdict(list)
        for argument in arguments:
            key = (argument.turn_name, self._normalize_text(argument.argument_text))
            by_text[key].append(argument)
        for group in by_text.values():
            ranked = sorted(
                group,
                key=lambda item: self._order_key(score_by_id[item.argument_id]),
                reverse=True,
            )
            duplicates.update(item.argument_id for item in ranked[1:])
        return duplicates

    def _order_key(self, score: DebateScore) -> tuple[float, float, float]:
        features = score.deterministic_features
        return (
            score.final_score,
            self._grounding_score(features),
            features.evidence_diversity,
        )

    def _cluster_arguments(
        self, arguments: list[DebateArgument]
    ) -> dict[str, list[DebateArgument]]:
        """Group proposals that compete for one slot.

        Sharing only a thesis type or a horizon is not competition: two claims
        about different things can both hold.
        """
        clusters: dict[str, list[DebateArgument]] = defaultdict(list)
        for argument in arguments:
            if argument.turn_name in {"challenge", "rebuttal"}:
                continue
            if argument.target_instrument:
                key = (
                    f"{argument.thesis_type.value}:"
                    f"{argument.target_instrument}:"
                    f"{argument.time_horizon or ''}"
                )
            else:
                key = f"claim:{argument.argument_id}"
            clusters[key].append(argument)
        return clusters

    def _pre_rank(
        self, arguments: list[DebateArgument], scores: dict[str, DebateScore]
    ) -> list[DebateArgument]:
        ordered = sorted(
            arguments,
            key=lambda argument: self._deterministic_total(
                scores[argument.argument_id].deterministic_features
            ),
            reverse=True,
        )
        if len(ordered) <= self.pairwise_limit:
            return ordered
        return ordered[: self.pre_rank_limit]

    def _run_pairwise(
        self,
        scores: dict[str, DebateScore],
        arguments: list[DebateArgument],
        *,
        judge: PairwiseJudge | None,
    ) -> None:
        for left, right in combinations(arguments, 2):
            result = judge(left, right) if judge else self.compare_arguments(
                left, right, scores=scores
            )
            if result == "left":
                scores[left.argument_id].pairwise_wins += 1
                scores[right.argument_id].pairwise_losses += 1
            elif result == "right":
                scores[right.argument_id].pairwise_wins += 1
                scores[left.argument_id].pairwise_losses += 1
            else:
                scores[left.argument_id].pairwise_ties += 1
                scores[right.argument_id].pairwise_ties += 1

    def compare_arguments(
        self,
        left: DebateArgument,
        right: DebateArgument,
        *,
        scores: dict[str, DebateScore],
    ) -> str:
        left_total = self._deterministic_total(
            scores[left.argument_id].deterministic_features
        )
        right_total = self._deterministic_total(
            scores[right.argument_id].deterministic_features
        )
        if abs(left_total - right_total) <= self.tie_threshold:
            return "tie"
        return "left" if left_total > right_total else "right"

    def _break_tie(
        self,
        score_by_id: dict[str, DebateScore],
        tied_arguments: list[DebateArgument],
    ) -> bool:
        grounding_scores = {
            argument.argument_id: self._grounding_score(
                score_by_id[argument.argument_id].deterministic_features
            )
            for argument in tied_arguments
        }
        best_grounding = max(grounding_scores.values())
        if list(grounding_scores.values()).count(best_grounding) == 1:
            return True

        diversity_scores = {
            argument.argument_id: score_by_id[
                argument.argument_id
            ].deterministic_features.evidence_diversity
            for argument in tied_arguments
        }
        best_diversity = max(diversity_scores.values())
        return list(diversity_scores.values()).count(best_diversity) == 1

    @staticmethod
    def _time_horizon_specificity(time_horizon: str | None) -> float:
        if not time_horizon:
            return 0.0
        normalized = time_horizon.strip().lower()
        if any(char.isdigit() for char in normalized):
            return 1.0
        if normalized in {"intraday", "days", "weeks", "months", "quarters"}:
            return 0.8
        if normalized in {"longer", "unknown"}:
            return 0.2
        return 0.5

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _grounding_score(features: DeterministicScoreFeature) -> float:
        return (
            min(1.0, features.evidence_count / 4.0) * 0.45
            + features.evidence_diversity * 0.35
            + features.assertion_alignment * 0.20
        )

    def _deterministic_total(self, features: DeterministicScoreFeature) -> float:
        total = self._grounding_score(features)
        total += features.time_horizon_specificity * 0.10
        total += features.conditional_clarity * 0.10
        total += (0.05 if features.is_actionable else 0.0)
        total += (0.05 if features.is_novel else -0.10)
        return max(0.0, min(1.0, total))

    @staticmethod
    def _pairwise_loss_rate(score: DebateScore) -> float:
        total = score.pairwise_wins + score.pairwise_losses + score.pairwise_ties
        if total == 0:
            return 0.0
        return (score.pairwise_losses + (score.pairwise_ties * 0.5)) / total
