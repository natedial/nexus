"""Helpers for building bounded forum-state payloads for debate rounds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_analysis_layer.models import (
    DebateArgument,
    DebateRelation,
    DebateScore,
    DebateSession,
    DebateVerdict,
    ForumContext,
)


@dataclass
class DebateSessionBuilder:
    """Build filtered forum context for later debate rounds."""

    max_arguments: int = 12
    max_relations: int = 24
    max_open_targets: int = 12

    def build_round_context(
        self,
        *,
        session: DebateSession,
        question_set: list[str] | None = None,
        budget: dict[str, int] | None = None,
        world_context: dict[str, Any] | None = None,
        target_selector: str | None = None,
    ) -> ForumContext:
        """Build the round-specific forum context.

        `target_selector` controls which argument subset is surfaced:
        - `proposal_targets`/`challenge_targets`: top-level arguments
        - `rebuttal_targets`: challenged arguments plus their attackers
        - `accepted_only`: accepted/synthesized arguments
        - `all`/None: all arguments
        """

        target_selector = (target_selector or "all").strip().lower()
        arguments = self._select_arguments(session, target_selector)
        allowed_ids = {argument.argument_id for argument in arguments}
        relations = [
            relation
            for relation in session.relations
            if relation.source_argument_id in allowed_ids
            or relation.target_argument_id in allowed_ids
        ][: self.max_relations]
        scores = [
            score for score in session.scores if score.argument_id in allowed_ids
        ]
        verdicts = [
            verdict for verdict in session.verdicts if verdict.argument_id in allowed_ids
        ]

        open_targets = self._select_open_targets(session, target_selector, allowed_ids)

        return ForumContext(
            research_id=session.research_id,
            document_hash=session.document_hash,
            analysis_version=session.analysis_version,
            run_id=session.run_id,
            question_set=list(question_set or self._default_question_set(session)),
            arguments=arguments,
            relations=relations,
            scores=scores,
            verdicts=verdicts,
            open_targets=open_targets,
            budget=dict(budget or {}),
            world_context=world_context,
        )

    def _select_arguments(
        self, session: DebateSession, target_selector: str
    ) -> list[DebateArgument]:
        arguments = list(session.arguments)
        if target_selector in {"proposal_targets", "challenge_targets"}:
            arguments = [argument for argument in arguments if not argument.target_claim_id]
        elif target_selector == "rebuttal_targets":
            challenged_ids = {
                relation.target_argument_id
                for relation in session.relations
                if relation.relation_type == "challenges"
            }
            attacker_ids = {
                relation.source_argument_id
                for relation in session.relations
                if relation.relation_type == "challenges"
            }
            allowed_ids = challenged_ids | attacker_ids
            arguments = [
                argument
                for argument in arguments
                if argument.argument_id in allowed_ids
                or argument.target_claim_id in challenged_ids
            ]
        elif target_selector == "accepted_only":
            accepted_ids = self._verdict_argument_ids(
                session, labels={"accepted", "synthesized"}
            )
            arguments = [
                argument
                for argument in arguments
                if argument.argument_id in accepted_ids
            ]

        arguments.sort(key=self._argument_sort_key)
        return arguments[: self.max_arguments]

    def _select_open_targets(
        self,
        session: DebateSession,
        target_selector: str,
        allowed_ids: set[str],
    ) -> list[str]:
        if target_selector in {"proposal_targets", "challenge_targets"}:
            targets = [
                argument.argument_id
                for argument in session.arguments
                if argument.argument_id in allowed_ids and not argument.target_claim_id
            ]
        elif target_selector == "rebuttal_targets":
            targets = [
                relation.target_argument_id
                for relation in session.relations
                if relation.relation_type == "challenges"
                and relation.target_argument_id in allowed_ids
            ]
        elif target_selector == "accepted_only":
            targets = sorted(allowed_ids)
        else:
            targets = sorted(allowed_ids)

        deduped: list[str] = []
        seen: set[str] = set()
        for target in targets:
            if target and target not in seen:
                deduped.append(target)
                seen.add(target)
        return deduped[: self.max_open_targets]

    @staticmethod
    def _argument_sort_key(argument: DebateArgument) -> tuple[int, str, str]:
        return (
            0 if argument.target_claim_id is None else 1,
            argument.turn_name,
            argument.argument_id,
        )

    @staticmethod
    def _default_question_set(session: DebateSession) -> list[str]:
        if not session.arguments:
            return ["What is the strongest supported interpretation of this document?"]

        prompts: list[str] = []
        for argument in session.arguments:
            if argument.target_instrument and argument.time_horizon:
                prompts.append(
                    f"What is the strongest view on {argument.target_instrument} over {argument.time_horizon}?"
                )
            elif argument.target_instrument:
                prompts.append(
                    f"What is the strongest view on {argument.target_instrument}?"
                )
            elif argument.time_horizon:
                prompts.append(
                    f"What is the strongest document-level view over the {argument.time_horizon} horizon?"
                )
        return prompts[:4] or [
            "Which arguments survive challenge strongly enough to guide synthesis?"
        ]

    @staticmethod
    def _verdict_argument_ids(
        session: DebateSession, *, labels: set[str]
    ) -> set[str]:
        accepted: set[str] = set()
        for verdict in session.verdicts:
            if verdict.verdict_label.value in labels:
                accepted.add(verdict.argument_id)
                accepted.update(verdict.synthesizes_from)
        return accepted

    @staticmethod
    def append_round_output(
        session: DebateSession,
        *,
        turn: Any,
        arguments: list[DebateArgument],
        relations: list[DebateRelation],
        scores: list[DebateScore],
        verdicts: list[DebateVerdict],
    ) -> DebateSession:
        """Return a session with round artifacts appended."""

        session.turns.append(turn)
        session.arguments.extend(arguments)
        session.relations.extend(relations)
        session.scores = DebateSessionBuilder._replace_by_id(
            session.scores, scores, key="score_id"
        )
        session.verdicts = DebateSessionBuilder._replace_by_id(
            session.verdicts, verdicts, key="verdict_id"
        )
        return session

    @staticmethod
    def _replace_by_id(existing: list[Any], incoming: list[Any], *, key: str) -> list[Any]:
        if not incoming:
            return list(existing)
        merged = {getattr(item, key): item for item in existing}
        for item in incoming:
            merged[getattr(item, key)] = item
        return list(merged.values())
