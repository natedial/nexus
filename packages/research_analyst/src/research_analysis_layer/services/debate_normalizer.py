"""Turn raw debate-agent JSON into validated debate artifacts.

Agents propose content. Identity, linkage, citation validity and provenance are
assigned here, so a model cannot collide with or overwrite another agent's
argument, cite text it was never given, or speak for another role. A malformed
item is dropped and reported; it never discards the rest of the turn.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from pydantic import ValidationError

from research_analysis_layer.models.debate_models import (
    ArgumentMetadata,
    DebateArgument,
    DebateRelation,
    DebateRelationType,
    DebateRoundOutput,
    DebateScore,
    DebateSession,
    DebateTurn,
    DebateVerdict,
    RebuttalStance,
    ThesisType,
)
from research_analysis_layer.services.agent_llm_client import AgentCallResult

logger = logging.getLogger(__name__)

_CITATION_FIELDS = ("cited_chunk_keys", "cited_evidence_keys", "cited_assertion_keys")
_CONTENT_FIELDS = (
    "argument_text",
    "thesis_type",
    "uncertainty",
    "qualifier_text",
    "target_instrument",
    "time_horizon",
    "invalidation_condition",
)
_DEFAULT_STRENGTH = 0.5


class DebateOutputNormalizer:
    """Normalize one round of agent results against the current session."""

    def __init__(
        self,
        *,
        session: DebateSession,
        round_name: str,
        turn_order: int,
        output_schema: str,
        allowed_ref_keys: Iterable[str],
        prompt_version_for: Callable[[str], str],
    ) -> None:
        self._session = session
        self._round_name = round_name
        self._turn_order = turn_order
        self._output_schema = output_schema
        self._allowed = set(allowed_ref_keys) | set(session.external_ref_keys)
        self._prompt_version_for = prompt_version_for
        self._session_ids = {item.argument_id for item in session.arguments}
        self._sequence = 0

    def normalize(self, result: AgentCallResult) -> DebateRoundOutput:
        agent_name = result.agent_name or "unknown"
        payload = result.parsed_output
        if self._output_schema != "DebateRoundOutput" or not isinstance(payload, dict):
            return DebateRoundOutput(
                turn=self._turn(
                    agent_name, [], "Round failed to emit structured debate output."
                ),
                error="invalid_round_output",
            )

        problems: list[str] = []
        targets = [
            resolved
            for resolved in map(
                self._session_ref, _as_list(payload, "target_argument_ids", problems)
            )
            if resolved is not None
        ]
        retrieved = [key for call in result.tool_calls for key in call.ref_keys]
        arguments, aliases = self._arguments(
            payload, result, targets, self._allowed | set(retrieved), problems
        )
        relations = self._relations(payload, agent_name, arguments, aliases, problems)
        scores: list[DebateScore] = []
        verdicts: list[DebateVerdict] = []
        if self._round_name == "adjudication":
            scores = self._scores(payload, agent_name, problems)
            verdicts = self._verdicts(payload, agent_name, problems)
        if not targets:
            targets = list(
                dict.fromkeys(relation.target_argument_id for relation in relations)
            )

        self._session.external_ref_keys.extend(
            key for key in retrieved if key not in self._session.external_ref_keys
        )
        if problems:
            logger.warning(
                "Debate turn %s/%s: %s", self._round_name, agent_name, "; ".join(problems)
            )
        return DebateRoundOutput(
            turn=self._turn(agent_name, targets, _turn_summary(payload)),
            arguments=arguments,
            relations=relations,
            scores=scores,
            verdicts=verdicts,
            error="; ".join(problems) or None,
        )

    def _turn(self, agent_name: str, targets: list[str], summary: str) -> DebateTurn:
        return DebateTurn(
            turn_id=(
                f"{self._session.session_id}:{self._round_name}:"
                f"{self._turn_order}:{agent_name}"
            ),
            session_id=self._session.session_id,
            turn_name=self._round_name,  # type: ignore[arg-type]
            turn_order=self._turn_order,
            agent_name=agent_name,
            target_argument_ids=targets,
            turn_summary=summary,
        )

    def _session_ref(self, ref: Any) -> str | None:
        """Resolve a full ID or short handle to an argument already in the session."""
        if not isinstance(ref, str) or not ref:
            return None
        if ref in self._session_ids:
            return ref
        full = f"{self._session.session_id}:{ref}"
        return full if full in self._session_ids else None

    def _arguments(
        self,
        payload: dict[str, Any],
        result: AgentCallResult,
        targets: list[str],
        allowed: set[str],
        problems: list[str],
    ) -> tuple[list[DebateArgument], dict[str, str]]:
        agent_name = result.agent_name or "unknown"
        arguments: list[DebateArgument] = []
        aliases: dict[str, str] = {}
        for raw in _as_list(payload, "arguments", problems):
            if not isinstance(raw, dict):
                problems.append("dropped argument: not an object")
                continue
            argument_id = (
                f"{self._session.session_id}:{self._round_name}:{self._sequence + 1}"
            )
            content = {
                name: raw[name] for name in _CONTENT_FIELDS if raw.get(name) is not None
            }
            content.setdefault(
                "thesis_type", _infer_thesis_type(agent_name, self._round_name)
            )
            dropped: list[str] = []
            for name in _CITATION_FIELDS:
                content[name] = []
                cited = raw.get(name)
                for key in cited if isinstance(cited, list) else []:
                    if isinstance(key, str) and key in allowed:
                        if key not in content[name]:
                            content[name].append(key)
                    else:
                        dropped.append(str(key))
            target = None
            if self._round_name != "proposal":
                target = self._session_ref(raw.get("target_claim_id"))
                if target is None and len(targets) == 1:
                    target = targets[0]
            raw_metadata = raw.get("metadata")
            raw_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
            try:
                argument = DebateArgument(
                    argument_id=argument_id,
                    session_id=self._session.session_id,
                    turn_name=self._round_name,
                    agent_name=agent_name,
                    target_claim_id=target,
                    metadata=ArgumentMetadata(
                        challenge_mode=raw_metadata.get("challenge_mode"),
                        rebuttal_stance=raw_metadata.get("rebuttal_stance"),
                        dropped_citations=dropped,
                        prompt_version=self._prompt_version_for(agent_name),
                        model_used=str(result.model_used or ""),
                        attempt_count=result.attempt_count,
                    ),
                    **content,
                )
            except ValidationError as exc:
                problems.append(f"dropped argument: {_summarize(exc)}")
                continue
            self._sequence += 1
            arguments.append(argument)
            aliases[argument_id] = argument_id
            aliases[f"{self._round_name}:{self._sequence}"] = argument_id
            for name in ("local_id", "argument_id"):
                alias = raw.get(name)
                if isinstance(alias, str) and alias:
                    aliases.setdefault(alias, argument_id)
        return arguments, aliases

    def _relations(
        self,
        payload: dict[str, Any],
        agent_name: str,
        arguments: list[DebateArgument],
        aliases: dict[str, str],
        problems: list[str],
    ) -> list[DebateRelation]:
        relations: list[DebateRelation] = []

        def add(kind: Any, source: str, target: str, raw: dict[str, Any]) -> None:
            fields = {
                name: raw[name]
                for name in ("strength", "explanation")
                if raw.get(name) is not None
            }
            try:
                relations.append(
                    DebateRelation(
                        relation_id=(
                            f"{self._session.session_id}:{self._round_name}:"
                            f"{agent_name}:relation:{len(relations) + 1}"
                        ),
                        session_id=self._session.session_id,
                        relation_type=kind,
                        source_argument_id=source,
                        target_argument_id=target,
                        **fields,
                    )
                )
            except ValidationError as exc:
                problems.append(f"dropped relation: {_summarize(exc)}")

        for raw in _as_list(payload, "relations", problems):
            if not isinstance(raw, dict):
                problems.append("dropped relation: not an object")
                continue
            raw_target = raw.get("target_argument_id")
            target = self._session_ref(raw_target) or aliases.get(str(raw_target))
            source = self._relation_source(raw, target, arguments, aliases, relations)
            if target is None and raw_target is None and source is not None:
                target = next(
                    item.target_claim_id
                    for item in arguments
                    if item.argument_id == source
                )
            if source is None or target is None or source == target:
                problems.append("dropped relation: unknown source or target")
                continue
            add(raw.get("relation_type"), source, target, raw)

        linked = {relation.source_argument_id for relation in relations}
        for argument in arguments:
            kind = _implied_relation(self._round_name, argument)
            if (
                kind is not None
                and argument.target_claim_id is not None
                and argument.argument_id not in linked
            ):
                add(
                    kind,
                    argument.argument_id,
                    argument.target_claim_id,
                    {"strength": _DEFAULT_STRENGTH},
                )
        return relations

    @staticmethod
    def _relation_source(
        raw: dict[str, Any],
        target: str | None,
        arguments: list[DebateArgument],
        aliases: dict[str, str],
        existing: list[DebateRelation],
    ) -> str | None:
        """An agent may only link from an argument it wrote in this response."""
        named = raw.get("source_argument_id")
        if named is not None:
            return aliases.get(str(named))
        if len(arguments) == 1:
            return arguments[0].argument_id
        used = {
            (item.source_argument_id, item.target_argument_id) for item in existing
        }
        matches = [
            item.argument_id
            for item in arguments
            if target is not None
            and item.target_claim_id == target
            and (item.argument_id, target) not in used
        ]
        return matches[0] if len(matches) == 1 else None

    def _scores(
        self, payload: dict[str, Any], agent_name: str, problems: list[str]
    ) -> list[DebateScore]:
        scores: list[DebateScore] = []
        for raw in _as_list(payload, "scores", problems):
            argument_id = (
                self._session_ref(raw.get("argument_id")) if isinstance(raw, dict) else None
            )
            if argument_id is None:
                problems.append("dropped score: unknown argument")
                continue
            try:
                scores.append(
                    DebateScore(
                        score_id=f"{self._session.session_id}:{agent_name}:score:{argument_id}",
                        session_id=self._session.session_id,
                        argument_id=argument_id,
                        llm_judge_score=raw.get("llm_judge_score"),
                    )
                )
            except ValidationError as exc:
                problems.append(f"dropped score: {_summarize(exc)}")
        return scores

    def _verdicts(
        self, payload: dict[str, Any], agent_name: str, problems: list[str]
    ) -> list[DebateVerdict]:
        verdicts: list[DebateVerdict] = []
        for raw in _as_list(payload, "verdicts", problems):
            argument_id = (
                self._session_ref(raw.get("argument_id")) if isinstance(raw, dict) else None
            )
            if argument_id is None:
                problems.append("dropped verdict: unknown argument")
                continue
            synthesized = raw.get("synthesizes_from")
            try:
                verdicts.append(
                    DebateVerdict(
                        verdict_id=f"{self._session.session_id}:{agent_name}:verdict:{argument_id}",
                        session_id=self._session.session_id,
                        argument_id=argument_id,
                        verdict_label=raw.get("verdict_label"),
                        reason=str(raw.get("reason") or ""),
                        synthesizes_from=[
                            resolved
                            for resolved in map(
                                self._session_ref,
                                synthesized if isinstance(synthesized, list) else [],
                            )
                            if resolved is not None
                        ],
                    )
                )
            except ValidationError as exc:
                problems.append(f"dropped verdict: {_summarize(exc)}")
        return verdicts


def _as_list(payload: dict[str, Any], name: str, problems: list[str]) -> list[Any]:
    value = payload.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"ignored {name}: not a list")
        return []
    return value


def _turn_summary(payload: dict[str, Any]) -> str:
    if payload.get("abstain") is True:
        return f"Abstained: {payload.get('abstain_reason') or 'no reason given'}"
    return str(payload.get("turn_summary") or "")


def _implied_relation(
    round_name: str, argument: DebateArgument
) -> DebateRelationType | None:
    if round_name == "challenge":
        return DebateRelationType.CHALLENGES
    if round_name == "rebuttal":
        if argument.metadata.rebuttal_stance == RebuttalStance.CONCEDE:
            return DebateRelationType.CONCEDES
        return DebateRelationType.REBUTS
    return None


def _infer_thesis_type(agent_name: str, round_name: str) -> ThesisType:
    if "position" in agent_name:
        return ThesisType.POSITIONING
    if "challeng" in agent_name or "rebut" in round_name:
        return ThesisType.CONTRARIAN
    return ThesisType.THESIS


def _summarize(exc: ValidationError) -> str:
    return ", ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['type']}"
        for error in exc.errors()
    )
