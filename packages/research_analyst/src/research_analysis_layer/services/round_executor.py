"""Round-based agent executor for multi-round analysis pipeline."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from research_analysis_layer.models.agent_outputs import (
    AgentExecutionMetadata,
    DocumentAnalysis,
    DocumentAngle,
    RoundTrace,
    ToolCallTrace,
)
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
)
from research_analysis_layer.services.agent_registry import AgentConfig, AgentRegistry

logger = logging.getLogger(__name__)


@dataclass
class RoundConfig:
    """Configuration for a round of agent execution."""

    name: str
    type: str  # "parallel" or "sequential"
    agents: list[str]
    receives: list[str]  # ["input", "specialists", etc.]
    fail_round_on_agent_error: bool = False


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
    ):
        self.registry = registry
        self.llm_client = llm_client
        self.input_builder = input_builder
        self.tool_registry = tool_registry

    def run(
        self,
        *,
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
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

        if self.tool_registry is not None:
            self.tool_registry.set_invocation_budget(max_total_tool_calls)

        try:
            for round_config in rounds:
                logger.info(
                    "Executing round: %s (%s)", round_config.name, round_config.type
                )

                merged_input = self._build_merged_input(
                    document=document,
                    chunks=chunks,
                    evidence_units=evidence_units,
                    assertions=assertions,
                    receives=round_config.receives,
                    prior_outputs=prior_outputs,
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

                if result.failed_count > 0 and round_config.fail_round_on_agent_error:
                    logger.error(
                        "Round %s failed due to agent errors", round_config.name
                    )
                    return None
        finally:
            if self.tool_registry is not None:
                self.tool_registry.clear_invocation_budget()

        return self._build_document_analysis(
            final_results=prior_outputs.get(rounds[-1].name, []),
            document=document,
            chunks=chunks,
            evidence_units=evidence_units,
            assertions=assertions,
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
                input_data[round_name] = [
                    self._extract_angle_from_result(r)
                    for r in prior_outputs[round_name]
                ]

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
                    logger.exception("Agent %s failed with exception", futures[future])
                    agent_results.append(self._create_error_result(str(e)))

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
            return self._create_error_result(f"Prompt not found for {agent_name}")

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
                    return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "Agent %s attempt %d failed: %s", agent_name, attempt + 1, e
                )

        return self._create_error_result(
            str(last_error) if last_error else "Max retries exceeded"
        )

    def _extract_angle_from_result(self, result: AgentCallResult) -> DocumentAngle:
        """Extract DocumentAngle from agent result."""
        if result.parsed_output and isinstance(result.parsed_output, dict):
            return DocumentAngle.model_validate(result.parsed_output)
        return DocumentAngle(
            angle="thesis",
            summary="No output available",
            key_claims=[],
            risks=[],
            confidence=0.0,
        )

    def _merge_sequential_input(
        self, current_input: dict[str, Any], result: AgentCallResult
    ) -> dict[str, Any]:
        """Merge agent result into input for next sequential agent."""
        new_input = dict(current_input)
        angle = self._extract_angle_from_result(result)
        new_input["last_result"] = angle.model_dump()
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

    def _build_document_analysis(
        self,
        *,
        final_results: list[AgentCallResult],
        document: Any,
        chunks: list[Any],
        evidence_units: list[Any],
        assertions: list[Any],
        run_id: int,
        analysis_version: str,
        round_traces: list[RoundTrace],
    ) -> DocumentAnalysis | None:
        """Build DocumentAnalysis from final round results."""
        if not final_results:
            return None

        result = final_results[0]
        if not result.parsed_output:
            return None

        parsed = result.parsed_output
        if isinstance(parsed, dict):
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
                "thesis": parsed.get("thesis", ""),
                "contrarian_view": parsed.get("contrarian_view", ""),
                "recommended_positioning": parsed.get("recommended_positioning", ""),
                "trading_opportunities": parsed.get("trading_opportunities", []),
                "short_time_horizon_insights": parsed.get(
                    "short_time_horizon_insights", []
                ),
                "talking_points": parsed.get("talking_points", []),
                "cross_document_references": parsed.get(
                    "cross_document_references", []
                ),
                "quality": parsed.get("quality"),
                "themes": parsed.get(
                    "themes", [c.model_dump() for c in chunks] if chunks else []
                ),
                "trades": parsed.get("trades"),
                "assertions": parsed.get(
                    "assertions",
                    [a.model_dump() for a in assertions] if assertions else [],
                ),
                "world_nodes": parsed.get("world_nodes", []),
                "world_edges": parsed.get("world_edges", []),
                "forecast_candidates": parsed.get("forecast_candidates", []),
            }
            parsed["quality"] = parsed["payload_json"].get("quality", {})
            parsed["themes"] = parsed["payload_json"].get("themes", [])
            parsed["trades"] = parsed["payload_json"].get("trades", [])
            parsed["assertions"] = parsed["payload_json"].get("assertions", [])
            parsed["world_nodes"] = parsed["payload_json"].get("world_nodes", [])
            parsed["world_edges"] = parsed["payload_json"].get("world_edges", [])
            parsed["forecast_candidates"] = parsed["payload_json"].get(
                "forecast_candidates", []
            )
            return DocumentAnalysis.model_validate(parsed)

        return None
