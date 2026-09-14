"""Deterministic scoring helpers for debate arguments."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
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

        clusters = self._cluster_arguments(arguments)
        for cluster in clusters.values():
            ranked = self._pre_rank(cluster, scores)
            if len(ranked) > 1:
                self._run_pairwise(scores, ranked, judge=judge)

        for score in scores.values():
            base = self._deterministic_total(score.deterministic_features)
            pairwise = self._pairwise_score(score)
            score.final_score = max(0.0, min(1.0, (base * 0.7) + (pairwise * 0.3)))

        verdicts = self.generate_verdicts(
            session_id=session_id,
            arguments=arguments,
            relations=relations,
            scores=list(scores.values()),
        )
        return list(scores.values()), verdicts

    def extract_features(
        self,
        *,
        argument: DebateArgument,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
    ) -> DeterministicScoreFeature:
        cited_refs = (
            list(argument.cited_chunk_keys)
            + list(argument.cited_evidence_keys)
            + list(argument.cited_assertion_keys)
        )
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
            len(argument.cited_assertion_keys) / max(1, len(argument.cited_chunk_keys) or 1),
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
    ) -> list[DebateVerdict]:
        score_by_id = {score.argument_id: score for score in scores}
        clusters = self._cluster_arguments(arguments)
        duplicate_ids = {
            relation.source_argument_id
            for relation in relations
            if relation.relation_type == DebateRelationType.DUPLICATES
        }
        verdicts: list[DebateVerdict] = []

        for cluster_arguments in clusters.values():
            ordered = sorted(
                cluster_arguments,
                key=lambda argument: (
                    score_by_id[argument.argument_id].final_score,
                    self._grounding_score(
                        score_by_id[argument.argument_id].deterministic_features
                    ),
                    score_by_id[argument.argument_id].deterministic_features.evidence_diversity,
                ),
                reverse=True,
            )
            top_score = score_by_id[ordered[0].argument_id].final_score
            tied = [
                argument
                for argument in ordered
                if abs(score_by_id[argument.argument_id].final_score - top_score)
                <= self.tie_threshold
            ]

            unresolved_tie = len(tied) > 1 and not self._break_tie(score_by_id, tied)
            if len({self._normalize_text(argument.argument_text) for argument in tied}) < len(tied):
                unresolved_tie = False
            seen_texts: set[str] = set()
            for argument in ordered:
                label = DebateVerdictLabel.REJECTED
                reason = "Lower-ranked within its competing cluster."
                normalized_text = self._normalize_text(argument.argument_text)
                is_duplicate_text = normalized_text in seen_texts
                seen_texts.add(normalized_text)

                if argument.argument_id in duplicate_ids or is_duplicate_text:
                    reason = "Duplicate of a stronger argument."
                elif unresolved_tie and argument in tied:
                    label = DebateVerdictLabel.CONTESTED
                    reason = "Near-tie after deterministic tie-breaks."
                elif argument.argument_id == ordered[0].argument_id:
                    label = (
                        DebateVerdictLabel.ACCEPTED
                        if top_score >= 0.35
                        else DebateVerdictLabel.NEEDS_MORE_EVIDENCE
                    )
                    reason = (
                        "Best-supported argument in its cluster."
                        if label == DebateVerdictLabel.ACCEPTED
                        else "Top argument remains weakly grounded."
                    )

                verdicts.append(
                    DebateVerdict(
                        verdict_id=f"{session_id}:verdict:{argument.argument_id}",
                        session_id=session_id,
                        argument_id=argument.argument_id,
                        verdict_label=label,
                        reason=reason,
                    )
                )

        return verdicts

    def _cluster_arguments(
        self, arguments: list[DebateArgument]
    ) -> dict[str, list[DebateArgument]]:
        clusters: dict[str, list[DebateArgument]] = defaultdict(list)
        for argument in arguments:
            if argument.target_claim_id:
                key = argument.target_claim_id
            elif argument.target_instrument or argument.time_horizon:
                key = (
                    f"{argument.thesis_type.value}:"
                    f"{argument.target_instrument or ''}:"
                    f"{argument.time_horizon or ''}"
                )
            else:
                key = f"{argument.thesis_type.value}:top"
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
        total -= 0.15 if features.has_contradiction else 0.0
        total -= 0.20 if features.has_accepted_contradiction else 0.0
        return max(0.0, min(1.0, total))

    @staticmethod
    def _pairwise_score(score: DebateScore) -> float:
        total = score.pairwise_wins + score.pairwise_losses + score.pairwise_ties
        if total == 0:
            return 0.0
        return (score.pairwise_wins + (score.pairwise_ties * 0.5)) / total
