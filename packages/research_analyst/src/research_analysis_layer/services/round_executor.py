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
                    result.agent_name = agent_name
                    return result
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
            return None

        result = final_results[0]
        if not result.parsed_output:
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
