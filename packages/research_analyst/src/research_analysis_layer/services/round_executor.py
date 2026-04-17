"""Round-based agent executor for multi-round analysis pipeline."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any

from research_analysis_layer.models.agent_outputs import (
    AgentExecutionMetadata,
    DocumentAnalysis,
    DocumentAngle,
    RoundTrace,
    ToolCallTrace,
)
from research_analysis_layer.models.debate_models import (
    DebateArgument,
    DebateRelation,
    DebateRoundOutput,
    DebateScore,
    DebateSession,
    DebateTurn,
    DebateVerdict,
    ThesisType,
)
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
)
from research_analysis_layer.services.agent_registry import AgentConfig, AgentRegistry
from research_analysis_layer.services.debate_ranker import DebateRanker
from research_analysis_layer.services.debate_session_builder import DebateSessionBuilder

logger = logging.getLogger(__name__)


@dataclass
class RoundConfig:
    """Configuration for a round of agent execution."""

    name: str
    type: str  # "parallel" or "sequential"
    agents: list[str]
    receives: list[str]  # ["input", "specialists", etc.]
    fail_round_on_agent_error: bool = False
    output_schema: str = ""
    writes_forum_state: bool = False
    receives_forum_state: bool = False
    target_selector: str | None = None


@dataclass
class AgentSpec:
    """Specification for running an agent."""

    name: str
    config: AgentConfig
    tools: list[dict[str, Any]]
    max_tool_calls: int
    timeout_seconds: int
    retry_count: int
    temperature: float
    output_schema: str


@dataclass
class RoundResult:
    """Result from executing a round."""

    round_name: str
    agent_results: list[AgentCallResult]
    duration_ms: int
    failed_count: int
    tool_call_count: int
    token_usage: TokenUsage = field(default_factory=TokenUsage)


class RoundExecutor:
    """Execute agents in rounds with parallel/sequential execution.

    This is the main orchestrator for the round-based pipeline.
    """

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        llm_client: Any,
        input_builder: AgentInputBuilder,
        tool_registry: Any | None = None,
        analysis_store: Any | None = None,
        session_builder: DebateSessionBuilder | None = None,
        debate_ranker: DebateRanker | None = None,
    ):
        self.registry = registry
        self.llm_client = llm_client
        self.input_builder = input_builder
        self.tool_registry = tool_registry
        self.analysis_store = analysis_store
        self.session_builder = session_builder or DebateSessionBuilder()
        self.debate_ranker = debate_ranker or DebateRanker()

    def run(
        self,
        *,
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        quality_report: Any | None = None,
        node_resolutions: list[Any] | None = None,
        edge_resolutions: list[Any] | None = None,
        forecast_candidates: list[Any] | None = None,
        run_id: int,
        analysis_version: str,
        rounds: list[RoundConfig],
        agent_specs: dict[str, AgentSpec],
        max_total_tool_calls: int | None = None,
    ) -> DocumentAnalysis | None:
        """Execute the round-based pipeline.

        Args:
            document: The document to analyze
            chunks: Extracted chunks
            evidence_units: Evidence units
            assertions: Extracted assertions
            run_id: The analysis run ID
            analysis_version: Version string
            rounds: List of round configurations
            agent_specs: Map of agent name to AgentSpec
            max_total_tool_calls: Total tool call budget for the run

        Returns:
            DocumentAnalysis from the final round, or None on failure
        """
        prior_outputs: dict[str, list[AgentCallResult]] = {}
        all_round_traces: list[RoundTrace] = []
        total_tool_calls = 0
        debate_session = self._initialize_debate_session(
            document=document,
            run_id=run_id,
            analysis_version=analysis_version,
            rounds=rounds,
        )

        if self.tool_registry is not None:
            self.tool_registry.set_invocation_budget(max_total_tool_calls)

        try:
            for turn_order, round_config in enumerate(rounds, start=1):
                logger.info(
                    "Executing round: %s (%s)", round_config.name, round_config.type
                )

                forum_context = None
                if debate_session is not None and round_config.receives_forum_state:
                    forum_context = self.session_builder.build_round_context(
                        session=debate_session,
                        target_selector=round_config.target_selector,
                        budget=self._build_forum_budget(
                            rounds=rounds,
                            turn_order=turn_order,
                            max_total_tool_calls=max_total_tool_calls,
                            total_tool_calls=total_tool_calls,
                        ),
                        world_context=self._build_world_context(
                            node_resolutions=node_resolutions or [],
                            edge_resolutions=edge_resolutions or [],
                        ),
                    )

                merged_input = self._build_merged_input(
                    document=document,
                    chunks=chunks,
                    evidence_units=evidence_units,
                    assertions=assertions,
                    receives=round_config.receives,
                    prior_outputs=prior_outputs,
                    forum_context=forum_context,
                )

                if round_config.type == "parallel":
                    result = self._execute_parallel_round(
                        round_config=round_config,
                        agent_specs=agent_specs,
                        merged_input=merged_input,
                        run_id=run_id,
                        analysis_version=analysis_version,
                        max_total_tool_calls=max_total_tool_calls,
                        total_tool_calls=total_tool_calls,
                    )
                else:
                    result = self._execute_sequential_round(
                        round_config=round_config,
                        agent_specs=agent_specs,
                        merged_input=merged_input,
                        run_id=run_id,
                        analysis_version=analysis_version,
                        max_total_tool_calls=max_total_tool_calls,
                        total_tool_calls=total_tool_calls,
                    )

                prior_outputs[round_config.name] = result.agent_results
                total_tool_calls += result.tool_call_count
                all_round_traces.append(self._build_round_trace(result))

                if debate_session is not None and round_config.writes_forum_state:
                    debate_outputs = self._collect_debate_round_outputs(
                        round_config=round_config,
                        result=result,
                        session=debate_session,
                        turn_order=turn_order,
                    )
                    if round_config.name == "adjudication":
                        debate_outputs = self._supplement_adjudication_outputs(
                            session=debate_session,
                            round_outputs=debate_outputs,
                        )
                    debate_session = self._persist_debate_round_outputs(
                        session=debate_session,
                        round_outputs=debate_outputs,
                    )

                if result.failed_count > 0 and round_config.fail_round_on_agent_error:
                    logger.error(
                        "Round %s failed due to agent errors", round_config.name
                    )
                    if debate_session is not None and self.analysis_store is not None:
                        self.analysis_store.update_debate_session_status(
                            debate_session.session_id, "abandoned"
                        )
                    return None
        finally:
            if self.tool_registry is not None:
                self.tool_registry.clear_invocation_budget()

        if debate_session is not None and self.analysis_store is not None:
            self.analysis_store.update_debate_session_status(
                debate_session.session_id, "completed"
            )

        return self._build_document_analysis(
            final_results=prior_outputs.get(rounds[-1].name, []),
            document=document,
            chunks=chunks,
            evidence_units=evidence_units,
            assertions=assertions,
            quality_report=quality_report,
            node_resolutions=node_resolutions or [],
            edge_resolutions=edge_resolutions or [],
            forecast_candidates=forecast_candidates or [],
            run_id=run_id,
            analysis_version=analysis_version,
            round_traces=all_round_traces,
        )

    def _build_merged_input(
        self,
        *,
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        receives: list[str],
        prior_outputs: dict[str, list[AgentCallResult]],
        forum_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the merged input for a round based on receives config."""
        input_data = {}

        if "input" in receives:
            input_data["base"] = self.input_builder.build(
                agent_type="synthetic",
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
            )

        for round_name in receives:
            if round_name == "input":
                continue
            if round_name in prior_outputs:
                extracted = [
                    payload
                    for payload in (
                        self._extract_payload_from_result(result)
                        for result in prior_outputs[round_name]
                    )
                    if payload is not None
                ]
                input_data[round_name] = extracted

        if forum_context is not None:
            input_data["forum_context"] = forum_context

        return input_data

    def _execute_parallel_round(
        self,
        *,
        round_config: RoundConfig,
        agent_specs: dict[str, AgentSpec],
        merged_input: dict[str, Any],
        run_id: int,
        analysis_version: str,
        max_total_tool_calls: int | None,
        total_tool_calls: int,
    ) -> RoundResult:
        """Execute agents in a round in parallel."""
        start_time = time.time()
        agent_results: list[AgentCallResult] = []

        def run_agent(agent_name: str) -> tuple[str, AgentCallResult]:
            spec = agent_specs[agent_name]
            effective_tools = spec.tools
            effective_max_calls = spec.max_tool_calls

            if max_total_tool_calls is not None:
                remaining = max_total_tool_calls - total_tool_calls
                if remaining <= 0:
                    effective_tools = []
                    effective_max_calls = 0
                elif effective_max_calls > remaining:
                    effective_max_calls = remaining

            result = self._run_agent(
                agent_name=agent_name,
                spec=spec,
                merged_input=merged_input,
                run_id=run_id,
                analysis_version=analysis_version,
                tools=effective_tools,
                max_tool_calls=effective_max_calls,
            )
            return agent_name, result

        with ThreadPoolExecutor(
            max_workers=min(4, len(round_config.agents))
        ) as executor:
            futures = {
                executor.submit(run_agent, name): name for name in round_config.agents
            }
            for future in as_completed(futures):
                try:
                    agent_name, result = future.result()
                    agent_results.append(result)
                except Exception as e:
                    failed_name = futures[future]
                    logger.exception("Agent %s failed with exception", failed_name)
                    err = self._create_error_result(str(e))
                    err.agent_name = failed_name
                    agent_results.append(err)

        duration_ms = int((time.time() - start_time) * 1000)
        return self._build_round_result(round_config.name, agent_results, duration_ms)

    def _execute_sequential_round(
        self,
        *,
        round_config: RoundConfig,
        agent_specs: dict[str, AgentSpec],
        merged_input: dict[str, Any],
        run_id: int,
        analysis_version: str,
        max_total_tool_calls: int | None,
        total_tool_calls: int,
    ) -> RoundResult:
        """Execute agents in a round sequentially."""
        start_time = time.time()
        agent_results: list[AgentCallResult] = []
        current_input = merged_input

        for agent_name in round_config.agents:
            spec = agent_specs[agent_name]
            effective_tools = spec.tools
            effective_max_calls = spec.max_tool_calls

            if max_total_tool_calls is not None:
                remaining = max_total_tool_calls - total_tool_calls
                if remaining <= 0:
                    effective_tools = []
                    effective_max_calls = 0
                elif effective_max_calls > remaining:
                    effective_max_calls = remaining

            result = self._run_agent(
                agent_name=agent_name,
                spec=spec,
                merged_input=current_input,
                run_id=run_id,
                analysis_version=analysis_version,
                tools=effective_tools,
                max_tool_calls=effective_max_calls,
            )
            agent_results.append(result)
            total_tool_calls += len(result.tool_calls)

            current_input = self._merge_sequential_input(current_input, result)

        duration_ms = int((time.time() - start_time) * 1000)
        return self._build_round_result(round_config.name, agent_results, duration_ms)

    def _run_agent(
        self,
        *,
        agent_name: str,
        spec: AgentSpec,
        merged_input: dict[str, Any],
        run_id: int,
        analysis_version: str,
        tools: list[dict[str, Any]],
        max_tool_calls: int,
    ) -> AgentCallResult:
        """Run a single agent with retries."""
        prompt = self.registry.load_prompt(agent_name)
        if not prompt:
            error_result = self._create_error_result(
                f"Prompt not found for {agent_name}"
            )
            error_result.agent_name = agent_name
            return error_result

        messages = self.input_builder.to_messages(merged_input)
        last_error = None

        for attempt in range(spec.retry_count):
            try:
                result = self.llm_client.generate_with_tools(
                    system_prompt=prompt,
                    messages=messages,
                    tools=tools,
                    model=spec.config.model,
                    max_tool_calls=max_tool_calls,
                    timeout_seconds=spec.timeout_seconds,
                )
                if result.parsed_output:
                    result.parsed_output = self._validate_parsed_output(
                        spec.output_schema, result.parsed_output
                    )
                    result.agent_name = agent_name
                    return result
                logger.warning(
                    "Agent %s attempt %d returned no parseable structured output; stop_reason=%s raw_text=%r",
                    agent_name,
                    attempt + 1,
                    result.stop_reason,
                    (result.raw_text or "")[:500],
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Agent %s attempt %d failed: %s", agent_name, attempt + 1, e
                )

        error_result = self._create_error_result(
            str(last_error) if last_error else "Max retries exceeded"
        )
        error_result.agent_name = agent_name
        return error_result

    def _extract_angle_from_result(self, result: AgentCallResult) -> DocumentAngle:
        """Extract a DocumentAngle from an agent result.

        Falls back to an empty DocumentAngle stamped with the correct angle
        when parsing or validation fails, so a failed specialist does not
        masquerade as a different specialist downstream.
        """
        from pydantic import ValidationError

        fallback_angle = self._fallback_angle_for(result.agent_name)

        if result.parsed_output and isinstance(result.parsed_output, dict):
            try:
                return DocumentAngle.model_validate(result.parsed_output)
            except ValidationError as e:
                logger.warning(
                    "Specialist %s returned invalid DocumentAngle: %s",
                    result.agent_name or "unknown",
                    e,
                )

        return DocumentAngle(
            angle=fallback_angle,
            summary="Specialist output unavailable",
            key_claims=[],
            cross_document_refs=[],
            risks=[],
            confidence=0.0,
        )

    @staticmethod
    def _fallback_angle_for(agent_name: str | None) -> str:
        """Map an agent name to its DocumentAngle.angle literal.

        Defaults to 'thesis' only when the agent name is unknown — which
        should not happen after this fix but is a safe default.
        """
        if agent_name in ("thesis", "contrarian", "positioning"):
            return agent_name
        return "thesis"

    def _merge_sequential_input(
        self, current_input: dict[str, Any], result: AgentCallResult
    ) -> dict[str, Any]:
        """Merge agent result into input for next sequential agent."""
        new_input = dict(current_input)
        last_result = self._extract_payload_from_result(result)
        if last_result is not None:
            new_input["last_result"] = last_result
        return new_input

    def _build_round_result(
        self, round_name: str, agent_results: list[AgentCallResult], duration_ms: int
    ) -> RoundResult:
        """Build RoundResult from agent results."""
        failed_count = sum(1 for r in agent_results if r.parsed_output is None)
        tool_call_count = sum(len(r.tool_calls) for r in agent_results)
        total_input = sum(r.token_usage.input_tokens for r in agent_results)
        total_output = sum(r.token_usage.output_tokens for r in agent_results)
        cache_read = sum(r.token_usage.cache_read_input_tokens for r in agent_results)
        cache_create = sum(
            r.token_usage.cache_creation_input_tokens for r in agent_results
        )

        return RoundResult(
            round_name=round_name,
            agent_results=agent_results,
            duration_ms=duration_ms,
            failed_count=failed_count,
            tool_call_count=tool_call_count,
            token_usage=TokenUsage(
                input_tokens=total_input,
                output_tokens=total_output,
                cache_read_input_tokens=cache_read,
                cache_creation_input_tokens=cache_create,
            ),
        )

    def _build_round_trace(self, result: RoundResult) -> RoundTrace:
        """Build RoundTrace from RoundResult."""
        return RoundTrace(
            round_name=result.round_name,
            duration_ms=result.duration_ms,
            agent_count=len(result.agent_results),
            failed_agent_count=result.failed_count,
            tool_call_count=result.tool_call_count,
            input_tokens=result.token_usage.input_tokens,
            output_tokens=result.token_usage.output_tokens,
            cache_read_input_tokens=result.token_usage.cache_read_input_tokens,
            cache_creation_input_tokens=result.token_usage.cache_creation_input_tokens,
        )

    def _create_error_result(self, error: str) -> AgentCallResult:
        """Create an error AgentCallResult."""
        return AgentCallResult(
            raw_text="",
            parsed_output=None,
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="",
            stop_reason="error",
            attempt_count=1,
        )

    @staticmethod
    def _build_debate_session_id(
        *,
        research_id: int,
        document_hash: str,
        analysis_version: str,
        run_id: int,
    ) -> str:
        return f"debate:{research_id}:{document_hash}:{analysis_version}:{run_id}"

    def _initialize_debate_session(
        self,
        *,
        document: Any,
        run_id: int,
        analysis_version: str,
        rounds: list[RoundConfig],
    ) -> DebateSession | None:
        if not any(
            round_config.writes_forum_state or round_config.receives_forum_state
            for round_config in rounds
        ):
            return None

        session = DebateSession(
            session_id=self._build_debate_session_id(
                research_id=document.research_id,
                document_hash=document.document_hash or "",
                analysis_version=analysis_version,
                run_id=run_id,
            ),
            research_id=document.research_id,
            document_hash=document.document_hash or "",
            analysis_version=analysis_version,
            run_id=run_id,
        )
        if self.analysis_store is not None:
            self.analysis_store.create_debate_session(
                session.session_id,
                session.research_id,
                session.document_hash,
                session.analysis_version,
                session.run_id,
            )
        return session

    def _build_forum_budget(
        self,
        *,
        rounds: list[RoundConfig],
        turn_order: int,
        max_total_tool_calls: int | None,
        total_tool_calls: int,
    ) -> dict[str, int]:
        budget = {"remaining_rounds": max(0, len(rounds) - turn_order)}
        if max_total_tool_calls is not None:
            budget["remaining_tool_calls"] = max(
                0, max_total_tool_calls - total_tool_calls
            )
        return budget

    @staticmethod
    def _build_world_context(
        *,
        node_resolutions: list[Any],
        edge_resolutions: list[Any],
    ) -> dict[str, Any] | None:
        if not node_resolutions and not edge_resolutions:
            return None
        return {
            "world_nodes": [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in node_resolutions
            ],
            "world_edges": [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in edge_resolutions
            ],
        }

    def _validate_parsed_output(
        self, output_schema: str, parsed_output: Any
    ) -> dict[str, Any]:
        if output_schema == "DocumentAngle":
            return DocumentAngle.model_validate(parsed_output).model_dump(mode="python")
        if output_schema == "DebateRoundOutput" and isinstance(parsed_output, dict):
            return parsed_output
        if isinstance(parsed_output, dict):
            return parsed_output
        return {"value": parsed_output}

    def _extract_payload_from_result(self, result: AgentCallResult) -> Any:
        if result.parsed_output is None:
            return None
        if isinstance(result.parsed_output, dict) and "angle" in result.parsed_output:
            return self._extract_angle_from_result(result)
        return result.parsed_output

    def _collect_debate_round_outputs(
        self,
        *,
        round_config: RoundConfig,
        result: RoundResult,
        session: DebateSession,
        turn_order: int,
    ) -> list[DebateRoundOutput]:
        outputs: list[DebateRoundOutput] = []
        for agent_result in result.agent_results:
            outputs.append(
                self._normalize_debate_round_output(
                    round_name=round_config.name,
                    output_schema=round_config.output_schema,
                    session=session,
                    agent_result=agent_result,
                    turn_order=turn_order,
                )
            )
        return outputs

    def _normalize_debate_round_output(
        self,
        *,
        round_name: str,
        output_schema: str,
        session: DebateSession,
        agent_result: AgentCallResult,
        turn_order: int,
    ) -> DebateRoundOutput:
        if output_schema != "DebateRoundOutput" or not isinstance(
            agent_result.parsed_output, dict
        ):
            turn = DebateTurn(
                turn_id=f"{session.session_id}:{round_name}:{turn_order}:{agent_result.agent_name or 'unknown'}",
                session_id=session.session_id,
                turn_name=round_name,  # type: ignore[arg-type]
                turn_order=turn_order,
                agent_name=agent_result.agent_name or "unknown",
                target_argument_ids=[],
                turn_summary="Round failed to emit structured debate output.",
            )
            return DebateRoundOutput(turn=turn, error="invalid_round_output")

        payload = dict(agent_result.parsed_output)
        target_argument_ids = list(payload.get("target_argument_ids") or [])
        arguments = self._normalize_debate_arguments(
            session=session,
            round_name=round_name,
            agent_name=agent_result.agent_name or "unknown",
            target_argument_ids=target_argument_ids,
            raw_arguments=payload.get("arguments") or [],
        )
        relations = self._normalize_debate_relations(
            session=session,
            raw_relations=payload.get("relations") or [],
            arguments=arguments,
            target_argument_ids=target_argument_ids,
        )
        if not target_argument_ids:
            target_argument_ids = self._collect_target_argument_ids(relations, arguments)
        scores = self._normalize_debate_scores(
            session=session,
            raw_scores=payload.get("scores") or [],
            target_argument_ids=target_argument_ids,
        )
        verdicts = self._normalize_debate_verdicts(
            session=session,
            raw_verdicts=payload.get("verdicts") or [],
            target_argument_ids=target_argument_ids,
        )
        turn = DebateTurn(
            turn_id=f"{session.session_id}:{round_name}:{turn_order}:{agent_result.agent_name or 'unknown'}",
            session_id=session.session_id,
            turn_name=round_name,  # type: ignore[arg-type]
            turn_order=turn_order,
            agent_name=agent_result.agent_name or "unknown",
            target_argument_ids=target_argument_ids,
            turn_summary=payload.get("turn_summary", ""),
        )
        return DebateRoundOutput(
            turn=turn,
            arguments=arguments,
            relations=relations,
            scores=scores,
            verdicts=verdicts,
        )

    def _normalize_debate_arguments(
        self,
        *,
        session: DebateSession,
        round_name: str,
        agent_name: str,
        target_argument_ids: list[str],
        raw_arguments: list[dict[str, Any]],
    ) -> list[DebateArgument]:
        arguments: list[DebateArgument] = []
        for index, raw_argument in enumerate(raw_arguments, start=1):
            payload = dict(raw_argument)
            payload.setdefault(
                "argument_id",
                f"{session.session_id}:{round_name}:{agent_name}:arg:{index}",
            )
            payload.setdefault("session_id", session.session_id)
            payload.setdefault("turn_name", round_name)
            payload.setdefault("agent_name", agent_name)
            payload.setdefault(
                "target_claim_id",
                target_argument_ids[0] if target_argument_ids else payload.get("target_claim_id"),
            )
            payload.setdefault(
                "thesis_type", self._infer_thesis_type(agent_name, round_name)
            )
            arguments.append(DebateArgument.model_validate(payload))
        return arguments

    def _normalize_debate_relations(
        self,
        *,
        session: DebateSession,
        raw_relations: list[dict[str, Any]],
        arguments: list[DebateArgument],
        target_argument_ids: list[str],
    ) -> list[DebateRelation]:
        relations: list[DebateRelation] = []
        default_source_id = arguments[0].argument_id if arguments else None
        default_target_id = target_argument_ids[0] if target_argument_ids else None
        for index, raw_relation in enumerate(raw_relations, start=1):
            payload = dict(raw_relation)
            payload.setdefault(
                "relation_id", f"{session.session_id}:relation:{len(session.relations) + index}"
            )
            payload.setdefault("session_id", session.session_id)
            payload.setdefault("source_argument_id", default_source_id)
            payload.setdefault("target_argument_id", default_target_id)
            relations.append(DebateRelation.model_validate(payload))
        return relations

    def _normalize_debate_scores(
        self,
        *,
        session: DebateSession,
        raw_scores: list[dict[str, Any]],
        target_argument_ids: list[str],
    ) -> list[DebateScore]:
        scores: list[DebateScore] = []
        for index, raw_score in enumerate(raw_scores, start=1):
            payload = dict(raw_score)
            payload.setdefault(
                "score_id", f"{session.session_id}:score:{payload.get('argument_id', index)}"
            )
            payload.setdefault("session_id", session.session_id)
            payload.setdefault(
                "argument_id",
                target_argument_ids[0] if target_argument_ids else payload.get("argument_id"),
            )
            scores.append(DebateScore.model_validate(payload))
        return scores

    def _normalize_debate_verdicts(
        self,
        *,
        session: DebateSession,
        raw_verdicts: list[dict[str, Any]],
        target_argument_ids: list[str],
    ) -> list[DebateVerdict]:
        verdicts: list[DebateVerdict] = []
        for index, raw_verdict in enumerate(raw_verdicts, start=1):
            payload = dict(raw_verdict)
            payload.setdefault(
                "verdict_id",
                f"{session.session_id}:verdict:{payload.get('argument_id', index)}",
            )
            payload.setdefault("session_id", session.session_id)
            payload.setdefault(
                "argument_id",
                target_argument_ids[0]
                if target_argument_ids
                else payload.get("argument_id"),
            )
            verdicts.append(DebateVerdict.model_validate(payload))
        return verdicts

    @staticmethod
    def _collect_target_argument_ids(
        relations: list[DebateRelation], arguments: list[DebateArgument]
    ) -> list[str]:
        target_ids = [relation.target_argument_id for relation in relations]
        if target_ids:
            return target_ids
        return [argument.target_claim_id for argument in arguments if argument.target_claim_id]

    @staticmethod
    def _infer_thesis_type(agent_name: str, round_name: str) -> ThesisType:
        if "position" in agent_name:
            return ThesisType.POSITIONING
        if "challeng" in agent_name or "rebut" in round_name:
            return ThesisType.CONTRARIAN
        return ThesisType.THESIS

    def _supplement_adjudication_outputs(
        self,
        *,
        session: DebateSession,
        round_outputs: list[DebateRoundOutput],
    ) -> list[DebateRoundOutput]:
        ranked_scores, ranked_verdicts = self.debate_ranker.rank_arguments(
            session_id=session.session_id,
            arguments=session.arguments,
            relations=session.relations,
        )

        supplemented: list[DebateRoundOutput] = []
        for round_output in round_outputs:
            scores = list(round_output.scores)
            verdicts = list(round_output.verdicts)
            existing_score_ids = {score.argument_id for score in scores}
            existing_verdict_ids = {verdict.argument_id for verdict in verdicts}

            for score in ranked_scores:
                if score.argument_id not in existing_score_ids:
                    scores.append(score)
            for verdict in ranked_verdicts:
                if verdict.argument_id not in existing_verdict_ids:
                    verdicts.append(verdict)
            supplemented.append(
                DebateRoundOutput(
                    turn=round_output.turn,
                    arguments=round_output.arguments,
                    relations=round_output.relations,
                    scores=scores,
                    verdicts=verdicts,
                    error=round_output.error,
                )
            )
        return supplemented

    def _persist_debate_round_outputs(
        self,
        *,
        session: DebateSession,
        round_outputs: list[DebateRoundOutput],
    ) -> DebateSession:
        for round_output in round_outputs:
            session = self.session_builder.append_round_output(
                session,
                turn=round_output.turn,
                arguments=round_output.arguments,
                relations=round_output.relations,
                scores=round_output.scores,
                verdicts=round_output.verdicts,
            )
            if self.analysis_store is not None:
                self.analysis_store.write_debate_turn(
                    round_output.turn.turn_id,
                    round_output.turn.session_id,
                    round_output.turn.turn_name,
                    round_output.turn.turn_order,
                    round_output.turn.agent_name,
                    round_output.turn.target_argument_ids,
                    round_output.turn.turn_summary,
                )
                self.analysis_store.write_debate_arguments(
                    [argument.model_dump(mode="json") for argument in round_output.arguments]
                )
                self.analysis_store.write_debate_relations(
                    [relation.model_dump(mode="json") for relation in round_output.relations]
                )
                self.analysis_store.write_debate_scores(
                    [score.model_dump(mode="json") for score in round_output.scores]
                )
                self.analysis_store.write_debate_verdicts(
                    [verdict.model_dump(mode="json") for verdict in round_output.verdicts]
                )
        return session

    @staticmethod
    def _canonical_document_key(
        *,
        research_id: int | None,
        document_hash: str | None,
        file_id: str | None,
    ) -> str:
        """Return the canonical document key, matching run_batch._document_key."""
        if file_id:
            return f"file:{file_id}"
        if research_id is not None and document_hash:
            return f"doc:{research_id}:{document_hash}"
        return ""

    def _build_document_analysis(
        self,
        *,
        final_results: list[AgentCallResult],
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        quality_report: Any | None = None,
        node_resolutions: list[Any] | None = None,
        edge_resolutions: list[Any] | None = None,
        forecast_candidates: list[Any] | None = None,
        run_id: int,
        analysis_version: str,
        round_traces: list[RoundTrace],
    ) -> DocumentAnalysis | None:
        """Build DocumentAnalysis from final round results."""
        if not final_results:
            logger.warning("No final synthesizer results available for document analysis")
            return None

        result = final_results[0]
        if not result.parsed_output:
            logger.warning(
                "Synthesizer produced no structured output; stop_reason=%s raw_text=%r",
                result.stop_reason,
                (result.raw_text or "")[:1000],
            )
            return None

        parsed = result.parsed_output
        if isinstance(parsed, dict):
            deterministic_payload = self._build_deterministic_payload(
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
                quality_report=quality_report,
                node_resolutions=node_resolutions or [],
                edge_resolutions=edge_resolutions or [],
                forecast_candidates=forecast_candidates or [],
            )
            # Orchestrator is authoritative for identity fields — the model
            # has no reliable way to know document_key or analysis_version.
            parsed["research_id"] = document.research_id
            parsed["document_hash"] = document.document_hash or ""
            parsed["analysis_version"] = analysis_version
            parsed["document_key"] = self._canonical_document_key(
                research_id=document.research_id,
                document_hash=document.document_hash,
                file_id=getattr(document, "file_id", None),
            )
            parsed["round_traces"] = [rt.model_dump() for rt in round_traces]
            parsed["metadata"] = {
                "research_id": document.research_id,
                "document_hash": document.document_hash,
                "analysis_version": analysis_version,
                "agent_type": "synthesizer",
                "model_requested": result.model_used,
                "model_used": result.model_used,
                "prompt_path": "",
                "prompt_version": "",
                "run_id": run_id,
                "attempt_count": result.attempt_count,
                "analyzed_at": datetime.now(timezone.utc).isoformat(),
            }
            parsed["payload_json"] = {
                "document": deterministic_payload["document"],
                "thesis": parsed.get("thesis", ""),
                "contrarian_view": parsed.get("contrarian_view", ""),
                "recommended_positioning": parsed.get("recommended_positioning", ""),
                "trading_opportunities": parsed.get("trading_opportunities") or [],
                "short_time_horizon_insights": (
                    parsed.get("short_time_horizon_insights") or []
                ),
                "talking_points": parsed.get("talking_points") or [],
                "cross_document_references": (
                    parsed.get("cross_document_references") or []
                ),
                "quality": parsed.get("quality") or deterministic_payload["quality"],
                "themes": parsed.get("themes") or deterministic_payload["themes"],
                "trades": parsed.get("trades") or deterministic_payload["trades"],
                "assertions": (
                    parsed.get("assertions") or deterministic_payload["assertions"]
                ),
                "world_nodes": (
                    parsed.get("world_nodes") or deterministic_payload["world_nodes"]
                ),
                "world_edges": (
                    parsed.get("world_edges") or deterministic_payload["world_edges"]
                ),
                "forecast_candidates": (
                    parsed.get("forecast_candidates")
                    or deterministic_payload["forecast_candidates"]
                ),
            }
            parsed["quality"] = parsed["payload_json"].get("quality", {})
            parsed["themes"] = parsed["payload_json"].get("themes", [])
            parsed["trades"] = parsed["payload_json"].get("trades", [])
            parsed["assertions"] = parsed["payload_json"].get("assertions", [])
            parsed["world_nodes"] = parsed["payload_json"].get("world_nodes", [])
            parsed["world_edges"] = parsed["payload_json"].get("world_edges", [])
            parsed["trading_opportunities"] = parsed["payload_json"].get(
                "trading_opportunities", []
            )
            parsed["short_time_horizon_insights"] = parsed["payload_json"].get(
                "short_time_horizon_insights", []
            )
            parsed["talking_points"] = parsed["payload_json"].get(
                "talking_points", []
            )
            parsed["cross_document_references"] = parsed["payload_json"].get(
                "cross_document_references", []
            )
            parsed["forecast_candidates"] = parsed["payload_json"].get(
                "forecast_candidates", []
            )
            return DocumentAnalysis.model_validate(parsed)

        return None

    def _build_deterministic_payload(
        self,
        *,
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        quality_report: Any | None,
        node_resolutions: list[Any],
        edge_resolutions: list[Any],
        forecast_candidates: list[Any],
    ) -> dict[str, Any]:
        """Build pipeline-owned payload sections from deterministic inputs."""
        parsed_doc = getattr(document, "document", None)
        parsed_data = parsed_doc.parsed_data if parsed_doc is not None else {}
        metadata = (
            parsed_data.get("metadata", {})
            if isinstance(parsed_data, dict)
            and isinstance(parsed_data.get("metadata"), dict)
            else {}
        )

        return {
            "document": {
                "research_id": getattr(document, "research_id", None),
                "file_id": getattr(document, "file_id", None),
                "document_hash": getattr(document, "document_hash", None),
                "document_name": getattr(parsed_doc, "document_name", None),
                "document_title": getattr(parsed_doc, "document_title", None),
                "source": getattr(parsed_doc, "source", None),
                "source_date": getattr(parsed_doc, "source_date", None),
                "publisher": getattr(parsed_doc, "publisher", None),
                "area": getattr(parsed_doc, "area", None),
                "region": getattr(parsed_doc, "region", None),
                "asset_focus": getattr(parsed_doc, "asset_focus", None),
                "document_link": getattr(parsed_doc, "document_link", None),
                "trade_count": getattr(parsed_doc, "trade_count", 0),
                "theme_count": getattr(parsed_doc, "theme_count", 0),
                "metadata": metadata,
            },
            "quality": self._quality_payload(quality_report),
            "themes": self._theme_payload(document),
            "trades": self._legacy_trade_payload(parsed_data),
            "chunks": [self._json_safe(chunk) for chunk in chunks],
            "evidence_units": [self._json_safe(unit) for unit in evidence_units],
            "assertions": [self._json_safe(assertion) for assertion in assertions],
            "world_nodes": [self._json_safe(node) for node in node_resolutions],
            "world_edges": [self._json_safe(edge) for edge in edge_resolutions],
            "forecast_candidates": [
                self._json_safe(candidate) for candidate in forecast_candidates
            ],
        }

    @staticmethod
    def _quality_payload(report: Any | None) -> dict[str, Any]:
        if report is None:
            return {}
        return {
            "score": getattr(report, "score", None),
            "passed": bool(getattr(report, "passed", False)),
            "warnings": list(getattr(report, "warnings", [])),
            "blocking_issues": list(getattr(report, "blocking_issues", [])),
            "metrics": dict(getattr(report, "metrics", {})),
        }

    @staticmethod
    def _theme_payload(document: Any) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for hydrated in getattr(document, "themes", []):
            theme = hydrated.theme
            payload.append(
                {
                    "theme_id": theme.id,
                    "theme_order": theme.theme_order,
                    "label": theme.label,
                    "scope": theme.scope,
                    "primary_category": theme.primary_category,
                    "relevance": list(theme.relevance),
                    "classification": theme.classification,
                    "strength": theme.strength,
                    "confidence": theme.confidence,
                    "evidence_count": theme.evidence_count,
                    "mention_count": theme.mention_count,
                    "context": theme.context,
                    "directionality": theme.directionality,
                    "argument_structure": theme.argument_structure,
                    "excerpts": [
                        excerpt.excerpt_text
                        for excerpt in getattr(hydrated, "excerpts", [])
                    ],
                }
            )
        return payload

    @staticmethod
    def _legacy_trade_payload(parsed_data: Any) -> list[dict[str, Any]]:
        if not isinstance(parsed_data, dict):
            return []
        trades = parsed_data.get("trades")
        if not isinstance(trades, list):
            return []
        return [trade for trade in trades if isinstance(trade, dict)]

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return cls._json_safe(value.model_dump())
        if is_dataclass(value):
            return cls._json_safe(asdict(value))
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(item) for item in value]
        return value
