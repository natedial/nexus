"""Round-based agent executor for multi-round analysis pipeline."""

from __future__ import annotations

import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ValidationError

from research_analysis_layer.models.agent_outputs import (
    ARGUMENT_MAP_VERSION,
    AgentExecutionMetadata,
    DocumentAnalysis,
    DocumentAngle,
    RoundTrace,
    ShortTimeHorizonInsight,
    TalkingPoint,
    ToolCallTrace,
    TradingOpportunity,
)
from research_analysis_layer.models.debate_models import (
    DebateRoundOutput,
    DebateSession,
)
from research_analysis_layer.parsed_payload import (
    identity_fields,
    legacy_metadata,
    legacy_trades,
)
from research_analysis_layer.services.figures import figures_for_document
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
)
from research_analysis_layer.services.agent_registry import AgentConfig, AgentRegistry
from research_analysis_layer.services.debate_normalizer import DebateOutputNormalizer
from research_analysis_layer.services.debate_ranker import DebateRanker
from research_analysis_layer.services.debate_session_builder import DebateSessionBuilder
from research_analysis_layer.services.debate_threads import select_thread_arguments
from research_analysis_layer.services.debate_verdicts import (
    JudgeBallot,
    build_open_disputes,
    resolve_verdicts,
)
from research_analysis_layer.services.model_family import model_family
from research_analysis_layer.services.tools.as_of import AsOfScope, parse_day

logger = logging.getLogger(__name__)

_NO_TOOLS_NOTE = (
    "Tools are unavailable in this run. Work only from the supplied payload and "
    "do not claim to have searched anything."
)


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
    # Agents see no authorship, scores or verdicts, and nothing from each other.
    blind: bool = False

    def __post_init__(self) -> None:
        if self.blind and self.type != "parallel":
            raise ValueError(
                f"blind round {self.name!r} must be parallel: sequential rounds "
                "pass one agent's output to the next"
            )


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


@dataclass
class RolloutStats:
    """Per-process counters for debate rollout observability."""

    shadow_runs_total: int = 0
    shadow_failures_total: int = 0
    shadow_debate_truncated_total: int = 0
    debate_fallbacks_total: int = 0
    baseline_input_tokens: int = 0
    baseline_output_tokens: int = 0
    debate_input_tokens: int = 0
    debate_output_tokens: int = 0
    baseline_duration_ms: int = 0
    debate_duration_ms: int = 0
    claim_rationale_rate: float | None = None
    claim_evidenced_rate: float | None = None
    divergence_grounded_rate: float | None = None
    divergence_attributed_rate: float | None = None
    consensus_multi_source_rate: float | None = None


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
        debate_mode: str = "off",
        debate_judge_model: str | None = None,
        max_debate_arguments: int = 8,
        provider_clients: dict[str, Any] | None = None,
    ):
        self.registry = registry
        self.llm_client = llm_client
        self.input_builder = input_builder
        self.tool_registry = tool_registry
        self.analysis_store = analysis_store
        self.session_builder = session_builder or DebateSessionBuilder()
        self.debate_ranker = debate_ranker or DebateRanker()
        self.debate_mode = debate_mode
        self.debate_judge_model = debate_judge_model
        self.max_debate_arguments = max_debate_arguments
        self.provider_clients = dict(provider_clients or {})
        self.rollout_stats = RolloutStats()
        self._last_synthesizer_input: dict[str, Any] | None = None

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
        session_truncated_flag: dict[str, bool] = {"v": False}
        agent_specs = self._apply_judge_model_override(agent_specs)
        allowed_ref_keys: set[str] = set()
        if debate_session is not None:
            allowed_ref_keys = self._allowed_argument_ref_keys(
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
                figure_keys=set(figures_for_document(document)),
            )

        if self.tool_registry is not None:
            self.tool_registry.set_invocation_budget(max_total_tool_calls)
            self.tool_registry.set_as_of_scope(self._as_of_scope(document))

        _debate_start = time.time() if self.debate_mode != "off" else None
        try:
            for turn_order, round_config in enumerate(rounds, start=1):
                if self.debate_mode == "off" and round_config.writes_forum_state:
                    logger.info(
                        "Skipping round %s (debate_mode=off)", round_config.name
                    )
                    continue
                logger.info(
                    "Executing round: %s (%s)", round_config.name, round_config.type
                )

                forum_context_dict: dict[str, Any] | None = None
                if debate_session is not None and round_config.receives_forum_state:
                    forum_context_model = self.session_builder.build_round_context(
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
                        blind=round_config.blind,
                    )
                    forum_context_raw = forum_context_model.model_dump()
                    forum_context_dict, truncated = self._apply_argument_cap(
                        forum_context_raw
                    )
                    if truncated:
                        self._note_truncation(
                            session_truncated_flag=session_truncated_flag
                        )

                merged_input = self._build_merged_input(
                    document=document,
                    chunks=chunks,
                    evidence_units=evidence_units,
                    assertions=assertions,
                    receives=round_config.receives,
                    prior_outputs=prior_outputs,
                    forum_context=forum_context_dict,
                )

                if round_config.output_schema == "DocumentAnalysis":
                    self._last_synthesizer_input = merged_input

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

                if round_config.writes_forum_state:
                    self.rollout_stats.debate_input_tokens += (
                        result.token_usage.input_tokens
                    )
                    self.rollout_stats.debate_output_tokens += (
                        result.token_usage.output_tokens
                    )

                if debate_session is not None and round_config.writes_forum_state:
                    debate_outputs = self._collect_debate_round_outputs(
                        round_config=round_config,
                        result=result,
                        session=debate_session,
                        turn_order=turn_order,
                        allowed_ref_keys=allowed_ref_keys,
                    )
                    if round_config.name == "adjudication":
                        debate_outputs = self._supplement_adjudication_outputs(
                            session=debate_session,
                            round_outputs=debate_outputs,
                            result=result,
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
        except Exception:
            if debate_session is not None and self.analysis_store is not None:
                self.analysis_store.update_debate_session_status(
                    debate_session.session_id, "abandoned"
                )
            raise
        finally:
            if self.tool_registry is not None:
                self.tool_registry.clear_invocation_budget()
                self.tool_registry.set_as_of_scope(None)

        if _debate_start is not None:
            self.rollout_stats.debate_duration_ms += int(
                (time.time() - _debate_start) * 1000
            )

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
            open_disputes=(
                build_open_disputes(
                    session_id=debate_session.session_id,
                    arguments=debate_session.arguments,
                    relations=debate_session.relations,
                    verdicts=debate_session.verdicts,
                )
                if debate_session is not None
                else []
            ),
        )

    def run_baseline_synthesis(
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
        synth_round: RoundConfig,
        synth_spec: AgentSpec,
    ) -> DocumentAnalysis | None:
        """Run the synthesizer with NO forum state injected. For shadow mode."""
        start = time.time()
        merged_input = self._build_merged_input(
            document=document,
            chunks=chunks,
            evidence_units=evidence_units,
            assertions=assertions,
            receives=synth_round.receives,
            prior_outputs={},
            forum_context=None,
        )
        if self.tool_registry is not None:
            self.tool_registry.set_as_of_scope(self._as_of_scope(document))
        try:
            result = self._execute_sequential_round(
                round_config=RoundConfig(
                    name=synth_round.name,
                    type="sequential",
                    agents=[synth_spec.name],
                    receives=synth_round.receives,
                    output_schema=synth_round.output_schema,
                ),
                agent_specs={synth_spec.name: synth_spec},
                merged_input=merged_input,
                run_id=run_id,
                analysis_version=analysis_version,
                max_total_tool_calls=None,
                total_tool_calls=0,
            )
        finally:
            if self.tool_registry is not None:
                self.tool_registry.set_as_of_scope(None)
        duration_ms = int((time.time() - start) * 1000)
        self.rollout_stats.baseline_input_tokens += result.token_usage.input_tokens
        self.rollout_stats.baseline_output_tokens += result.token_usage.output_tokens
        self.rollout_stats.baseline_duration_ms += duration_ms

        return self._build_document_analysis(
            final_results=result.agent_results,
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
            round_traces=[self._build_round_trace(result)],
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

        client = self._client_for(spec)
        if client is None:
            error_result = self._create_error_result(
                f"No client for provider {spec.config.provider!r}"
            )
            error_result.agent_name = agent_name
            return error_result

        messages = self.input_builder.to_messages(merged_input)
        if getattr(client, "supports_tools", True) is False:
            tools, max_tool_calls = [], 0
        configured_tools = getattr(spec.config, "tools", None)
        if isinstance(configured_tools, list) and configured_tools and not tools:
            messages = [*messages, {"role": "user", "content": _NO_TOOLS_NOTE}]
        last_error = None

        for attempt in range(spec.retry_count):
            try:
                result = client.generate_with_tools(
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

    @staticmethod
    def _as_of_scope(document: Any) -> AsOfScope:
        return AsOfScope(
            as_of=parse_day(
                getattr(getattr(document, "document", None), "source_date", None)
            ),
            exclude_research_id=getattr(document, "research_id", None),
        )

    def _client_for(self, spec: AgentSpec) -> Any | None:
        provider = getattr(spec.config, "provider", None)
        if not isinstance(provider, str) or not provider:
            return self.llm_client
        client = self.provider_clients.get(provider)
        if client is None:
            logger.warning(
                "Agent %s needs provider %s, which is not configured", spec.name, provider
            )
        return client

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
        if self.debate_mode == "off":
            return None
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
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in node_resolutions
            ],
            "world_edges": [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in edge_resolutions
            ],
        }

    def _apply_argument_cap(
        self, forum_context: dict[str, Any] | None
    ) -> tuple[dict[str, Any] | None, bool]:
        """Trim forum arguments to max_debate_arguments. Returns (context, truncated)."""
        if forum_context is None:
            return None, False
        args = forum_context.get("arguments") or []
        if len(args) <= self.max_debate_arguments:
            return forum_context, False
        kept = select_thread_arguments(args, self.max_debate_arguments)
        kept_ids = {a.get("argument_id") for a in kept}
        trimmed = dict(forum_context)
        trimmed["arguments"] = kept
        trimmed["relations"] = [
            r
            for r in (forum_context.get("relations") or [])
            if r.get("source_argument_id") in kept_ids
            and r.get("target_argument_id") in kept_ids
        ]
        for name in ("scores", "verdicts"):
            trimmed[name] = [
                item
                for item in (forum_context.get(name) or [])
                if item.get("argument_id") in kept_ids
            ]
        trimmed["open_targets"] = [
            target
            for target in (forum_context.get("open_targets") or [])
            if target in kept_ids
        ]
        trimmed["omitted_argument_count"] = (
            forum_context.get("omitted_argument_count") or 0
        ) + (len(args) - len(kept))
        return trimmed, True

    def _note_truncation(self, *, session_truncated_flag: dict[str, bool]) -> None:
        """Bump shadow_debate_truncated_total once per session."""
        if session_truncated_flag["v"]:
            return
        session_truncated_flag["v"] = True
        self.rollout_stats.shadow_debate_truncated_total += 1

    def _apply_judge_model_override(
        self, agent_specs: dict[str, AgentSpec]
    ) -> dict[str, AgentSpec]:
        if not self.debate_judge_model or "adjudicator" not in agent_specs:
            return agent_specs
        original = agent_specs["adjudicator"]
        from dataclasses import replace

        new_config = replace(original.config, model=self.debate_judge_model)
        return {
            **agent_specs,
            "adjudicator": replace(original, config=new_config),
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
        allowed_ref_keys: set[str],
    ) -> list[DebateRoundOutput]:
        normalizer = DebateOutputNormalizer(
            session=session,
            round_name=round_config.name,
            turn_order=turn_order,
            output_schema=round_config.output_schema,
            allowed_ref_keys=allowed_ref_keys,
            prompt_version_for=self._prompt_version,
        )
        # Parallel agents finish in any order; config order keeps IDs stable.
        order = {name: index for index, name in enumerate(round_config.agents)}
        ordered = sorted(
            result.agent_results,
            key=lambda item: order.get(item.agent_name or "", len(order)),
        )
        return [normalizer.normalize(agent_result) for agent_result in ordered]

    def _prompt_version(self, agent_name: str) -> str:
        try:
            prompt = self.registry.load_prompt(agent_name)
        except Exception as exc:
            logger.warning("Prompt could not be loaded for %s: %s", agent_name, exc)
            return ""
        if not isinstance(prompt, str) or not prompt:
            return ""
        return f"prompt:{hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16]}"

    def _supplement_adjudication_outputs(
        self,
        *,
        session: DebateSession,
        round_outputs: list[DebateRoundOutput],
        result: RoundResult,
    ) -> list[DebateRoundOutput]:
        """Replace raw judge rulings with resolved verdicts for every argument."""
        ranked_scores, ranked_verdicts = self.debate_ranker.rank_arguments(
            session_id=session.session_id,
            arguments=session.arguments,
            relations=session.relations,
        )
        model_by_agent = {item.agent_name: item.model_used for item in result.agent_results}
        scores, verdicts = resolve_verdicts(
            arguments=session.arguments,
            relations=session.relations,
            ranked_scores=ranked_scores,
            ranked_verdicts=ranked_verdicts,
            ballots=[
                JudgeBallot.from_round_output(
                    output, family=model_family(model_by_agent.get(output.turn.agent_name))
                )
                for output in round_outputs
            ],
        )
        resolved = [
            output.model_copy(update={"scores": [], "verdicts": []})
            for output in round_outputs
        ]
        if resolved:
            resolved[0] = resolved[0].model_copy(
                update={"scores": scores, "verdicts": verdicts}
            )
        return resolved

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
                    [
                        argument.model_dump(mode="json")
                        for argument in round_output.arguments
                    ]
                )
                self.analysis_store.write_debate_relations(
                    [
                        relation.model_dump(mode="json")
                        for relation in round_output.relations
                    ]
                )
                self.analysis_store.write_debate_scores(
                    [score.model_dump(mode="json") for score in round_output.scores]
                )
                self.analysis_store.write_debate_verdicts(
                    [
                        verdict.model_dump(mode="json")
                        for verdict in round_output.verdicts
                    ]
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
        open_disputes: list[dict[str, Any]] | None = None,
    ) -> DocumentAnalysis | None:
        """Build DocumentAnalysis from final round results."""
        if not final_results:
            logger.warning(
                "No final synthesizer results available for document analysis"
            )
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
            parsed["open_disputes"] = list(open_disputes or [])
            parsed["round_traces"] = [rt.model_dump() for rt in round_traces]
            agent_name = (
                result.agent_name
                if isinstance(result.agent_name, str) and result.agent_name
                else "synthesizer"
            )
            prompt_path, prompt_version = self._synthesizer_prompt_stamp(agent_name)
            parsed["metadata"] = {
                "research_id": document.research_id,
                "document_hash": document.document_hash,
                "analysis_version": analysis_version,
                "agent_type": "synthesizer",
                "model_requested": result.model_used,
                "model_used": result.model_used,
                "prompt_path": prompt_path,
                "prompt_version": prompt_version,
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
                "open_disputes": parsed["open_disputes"],
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
            parsed["trading_opportunities"] = self._coerce_model_list(
                TradingOpportunity,
                parsed["payload_json"].get("trading_opportunities"),
                "trading_opportunities",
            )
            parsed["short_time_horizon_insights"] = self._coerce_model_list(
                ShortTimeHorizonInsight,
                parsed["payload_json"].get("short_time_horizon_insights"),
                "short_time_horizon_insights",
            )
            parsed["talking_points"] = self._coerce_model_list(
                TalkingPoint,
                parsed["payload_json"].get("talking_points"),
                "talking_points",
            )
            parsed["payload_json"]["trading_opportunities"] = parsed[
                "trading_opportunities"
            ]
            parsed["payload_json"]["short_time_horizon_insights"] = parsed[
                "short_time_horizon_insights"
            ]
            parsed["payload_json"]["talking_points"] = parsed["talking_points"]
            parsed["cross_document_references"] = parsed["payload_json"].get(
                "cross_document_references", []
            )
            parsed["forecast_candidates"] = parsed["payload_json"].get(
                "forecast_candidates", []
            )
            figures_by_key = figures_for_document(document)
            parsed["argument_map"] = self._coerce_argument_map(
                parsed.get("argument_map"),
                allowed_ref_keys=self._allowed_argument_ref_keys(
                    document=document,
                    chunks=chunks,
                    evidence_units=evidence_units,
                    assertions=assertions,
                    figure_keys=set(figures_by_key),
                ),
                figures_by_key=figures_by_key,
            )
            parsed["argument_map_meta"] = {
                "extractor_version": ARGUMENT_MAP_VERSION,
                "run_id": run_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            return DocumentAnalysis.model_validate(parsed)

        return None

    @staticmethod
    def _field_max_length(field: Any) -> int | None:
        for meta in getattr(field, "metadata", ()) or ():
            max_length = getattr(meta, "max_length", None)
            if max_length is not None:
                return int(max_length)
        return None

    @classmethod
    def _clamp_string_constraints(
        cls, model_cls: Any, item: dict[str, Any]
    ) -> dict[str, Any]:
        clamped = dict(item)
        for name, field in model_cls.model_fields.items():
            value = clamped.get(name)
            if not isinstance(value, str):
                continue
            max_length = cls._field_max_length(field)
            if max_length is not None and len(value) > max_length:
                logger.warning(
                    "%s.%s exceeds max_length=%s; truncating from %s chars",
                    model_cls.__name__,
                    name,
                    max_length,
                    len(value),
                )
                clamped[name] = value[:max_length]
        return clamped

    @classmethod
    def _coerce_model_list(
        cls, model_cls: Any, raw: object, label: str
    ) -> list[dict[str, Any]]:
        """Keep valid items; truncate over-long strings; drop the rest."""
        if not isinstance(raw, list):
            return []
        kept: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                logger.warning("%s: dropping non-object item", label)
                continue
            clamped = cls._clamp_string_constraints(model_cls, item)
            try:
                kept.append(model_cls.model_validate(clamped).model_dump(mode="json"))
            except ValidationError as e:
                logger.warning("%s: dropping invalid item: %s", label, e)
        return kept

    def _synthesizer_prompt_stamp(self, agent_name: str) -> tuple[str, str]:
        """Path and ``prompt:<sha256[:16]>`` for the prompt that actually ran.

        Both fields stay empty when the include-resolved prompt cannot be loaded.
        """
        try:
            path = self.registry.resolve_prompt_path(agent_name)
            prompt = self.registry.load_prompt(agent_name)
        except Exception as exc:
            logger.warning(
                "Synthesizer prompt could not be loaded for %s: %s",
                agent_name,
                exc,
            )
            return "", ""
        if path is None or not isinstance(prompt, str) or not prompt:
            return "", ""
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return str(path), f"prompt:{digest}"

    @staticmethod
    def _value(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _add_ref_key(cls, keys: set[str], value: Any) -> None:
        if isinstance(value, str) and value:
            keys.add(value)

    @classmethod
    def _allowed_argument_ref_keys(
        cls,
        *,
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        figure_keys: set[str] | None = None,
    ) -> set[str]:
        """Keys the model was given, matching AgentInputBuilder."""
        keys: set[str] = set()
        for chunk in chunks:
            order = cls._value(chunk, "chunk_order")
            if isinstance(order, int) and not isinstance(order, bool):
                keys.add(f"chunk-{order}")
            span_keys = cls._value(chunk, "span_keys") or []
            if isinstance(span_keys, (list, tuple)):
                for span_key in span_keys:
                    cls._add_ref_key(keys, span_key)
            cls._add_ref_key(keys, cls._value(chunk, "retrieval_chunk_key"))
        for unit in evidence_units:
            order = cls._value(unit, "chunk_order")
            evidence_order = cls._value(unit, "evidence_order")
            if isinstance(order, int) and not isinstance(order, bool):
                keys.add(f"chunk-{order}")
                if isinstance(evidence_order, int) and not isinstance(evidence_order, bool):
                    keys.add(f"chunk-{order}:evidence-{evidence_order}")
        for assertion in assertions:
            order = cls._value(assertion, "chunk_order")
            assertion_order = cls._value(assertion, "assertion_order")
            if isinstance(order, int) and not isinstance(order, bool):
                keys.add(f"chunk-{order}")
                if isinstance(assertion_order, int) and not isinstance(
                    assertion_order, bool
                ):
                    keys.add(f"chunk-{order}:assertion-{assertion_order}")
        spans = cls._value(document, "spans") or []
        if isinstance(spans, (list, tuple)):
            for span in spans:
                cls._add_ref_key(keys, cls._value(span, "span_key"))
                metadata = cls._value(span, "metadata") or {}
                if isinstance(metadata, dict):
                    cls._add_ref_key(keys, metadata.get("figure_key"))
        for figure_key in figure_keys or ():
            cls._add_ref_key(keys, figure_key)
        return keys

    @staticmethod
    def _clear_unknown_ref_keys(item: dict, allowed_ref_keys: set[str]) -> dict:
        """Null ref_keys the model was not given. Leave claim text and referent_key."""
        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            return item
        cleaned: list[Any] = []
        changed = False
        for ref in evidence:
            if isinstance(ref, dict) and ref.get("ref_key") not in allowed_ref_keys:
                if ref.get("ref_key") is not None:
                    ref = dict(ref)
                    ref["ref_key"] = None
                    changed = True
            cleaned.append(ref)
        if not changed:
            return item
        updated = dict(item)
        updated["evidence"] = cleaned
        return updated

    @classmethod
    def _coerce_argument_map(
        cls,
        raw: object,
        allowed_ref_keys: set[str] | None = None,
        figures_by_key: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict]:
        """Keep well-formed ClaimNode dicts; log and drop the rest.

        Unknown ref_keys are cleared, then ClaimNode downgrades ``evidenced``
        claims that no longer cite a real key. Claims and evidence text stay.
        A chart ref_key that matches a figure copies that figure onto the evidence.
        """
        from research_analysis_layer.models.agent_outputs import ClaimNode

        if not isinstance(raw, list):
            return []
        allowed = allowed_ref_keys if allowed_ref_keys is not None else set()
        kept: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                logger.warning("argument_map: dropping non-object item")
                continue
            if allowed_ref_keys is not None:
                item = cls._clear_unknown_ref_keys(item, allowed)
            try:
                dumped = ClaimNode.model_validate(item).model_dump()
            except ValidationError as e:
                logger.warning("argument_map: dropping invalid claim: %s", e)
                continue
            if figures_by_key:
                cls._attach_figures(dumped, figures_by_key)
            kept.append(dumped)
        return kept

    @staticmethod
    def _attach_figures(claim: dict, figures_by_key: dict[str, dict[str, Any]]) -> None:
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            return
        for ref in evidence:
            if not isinstance(ref, dict):
                continue
            figure = figures_by_key.get(ref.get("ref_key"))
            if figure is not None:
                ref["figure"] = dict(figure)

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
                "identity": identity_fields(parsed_data),
                "metadata": legacy_metadata(parsed_data),
            },
            "quality": self._quality_payload(quality_report),
            "themes": self._theme_payload(document),
            "trades": legacy_trades(parsed_data),
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

    @classmethod
    def _json_safe(cls, value: Any, *, _depth: int = 0) -> Any:
        """Convert nested values into JSON-friendly primitives.

        Uses ``isinstance(..., BaseModel)`` rather than ``hasattr(..., "model_dump")``.
        MagicMock and similar proxies advertise every attribute, so a bare hasattr
        check recurses forever and can grow RSS into the multi-GB range.
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if _depth > 64:
            return str(value)
        if isinstance(value, BaseModel):
            return cls._json_safe(value.model_dump(mode="python"), _depth=_depth + 1)
        if is_dataclass(value) and not isinstance(value, type):
            return cls._json_safe(asdict(value), _depth=_depth + 1)
        if isinstance(value, SimpleNamespace):
            return cls._json_safe(vars(value), _depth=_depth + 1)
        if isinstance(value, dict):
            return {
                str(key): cls._json_safe(item, _depth=_depth + 1)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item, _depth=_depth + 1) for item in value]
        return value
