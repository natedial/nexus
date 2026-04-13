"""Execution engine for document analysis agents."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any

from pydantic import BaseModel

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import (
    AgentExecutionMetadata,
    AnalysisChunkDraft,
    AssertionDraft,
    EvidenceUnitDraft,
    HydratedParsedDocument,
    ShortTimeHorizonAnalysis,
    TalkingPointsAnalysis,
    TradingAnalysis,
)
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.agent_llm_client import AgentLlmClient
from research_analysis_layer.services.agent_registry import AgentConfig, AgentRegistry


@dataclass(slots=True)
class AgentExecutionSummary:
    """Aggregate result summary across all executed agents."""

    success_count: int = 0
    no_output_count: int = 0
    error_count: int = 0


@dataclass(slots=True)
class _AgentAttemptResult:
    agent_type: str
    status: str
    metadata: AgentExecutionMetadata
    payload: BaseModel | None = None
    error_type: str | None = None
    error_text: str | None = None


class AgentExecutor:
    """Execute configured agents over one document."""

    _MODEL_BY_AGENT = {
        "trading_opportunities": TradingAnalysis,
        "short_time_horizon": ShortTimeHorizonAnalysis,
        "talking_points": TalkingPointsAnalysis,
    }

    def __init__(
        self,
        *,
        store: AnalysisStore,
        registry: AgentRegistry,
        llm_client: AgentLlmClient | None,
        input_builder: AgentInputBuilder,
    ):
        self.store = store
        self.registry = registry
        self.llm_client = llm_client
        self.input_builder = input_builder

    def execute(
        self,
        *,
        document: HydratedParsedDocument,
        chunks: list[AnalysisChunkDraft],
        evidence_units: list[EvidenceUnitDraft],
        assertions: list[AssertionDraft],
        run_id: int,
        analysis_version: str,
        selected_agents: list[str] | None = None,
    ) -> AgentExecutionSummary:
        if self.llm_client is None:
            return AgentExecutionSummary()
        configs = self._resolve_configs(selected_agents)
        if not configs:
            return AgentExecutionSummary()

        future_results = []
        max_workers = min(4, len(configs))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for config in configs:
                future_results.append(
                    executor.submit(
                        self._run_agent,
                        config=config,
                        document=document,
                        chunks=chunks,
                        evidence_units=evidence_units,
                        assertions=assertions,
                        run_id=run_id,
                        analysis_version=analysis_version,
                    )
                )

            results = [future.result() for future in as_completed(future_results)]

        summary = AgentExecutionSummary()
        for result in results:
            self.store.upsert_agent_result(result.agent_type, result)
            if result.status == "success":
                summary.success_count += 1
            elif result.status == "no_output":
                summary.no_output_count += 1
            else:
                summary.error_count += 1
        return summary

    def _resolve_configs(self, selected_agents: list[str] | None) -> list[AgentConfig]:
        configs = self.registry.list_agents()
        if not selected_agents or "all" in selected_agents:
            return [config for config in configs if config.name in self._MODEL_BY_AGENT]
        selected = set(selected_agents)
        return [
            config
            for config in configs
            if config.name in selected and config.name in self._MODEL_BY_AGENT
        ]

    def _run_agent(
        self,
        *,
        config: AgentConfig,
        document: HydratedParsedDocument,
        chunks: list[AnalysisChunkDraft],
        evidence_units: list[EvidenceUnitDraft],
        assertions: list[AssertionDraft],
        run_id: int,
        analysis_version: str,
    ) -> _AgentAttemptResult:
        prompt = self.registry.load_prompt(config.name)
        if not prompt:
            metadata = self._metadata(
                config=config,
                document=document,
                analysis_version=analysis_version,
                run_id=run_id,
                model_used=config.model,
                attempt_count=0,
                prompt_version="missing_prompt",
            )
            return _AgentAttemptResult(
                agent_type=config.name,
                status="error",
                metadata=metadata,
                error_type="missing_prompt",
                error_text=f"prompt not found for {config.name}",
            )

        prompt_version = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        payload = self.input_builder.build(
            agent_type=config.name,
            document=document,
            chunks=chunks,
            evidence_units=evidence_units,
            assertions=assertions,
        )
        model_class = self._MODEL_BY_AGENT[config.name]
        total_attempts = 0
        last_error: Exception | None = None
        models_to_try = [config.model]
        if config.fallback_model and config.fallback_model != config.model:
            models_to_try.append(config.fallback_model)

        for model_name in models_to_try:
            for _ in range(config.retry_count):
                total_attempts += 1
                metadata = self._metadata(
                    config=config,
                    document=document,
                    analysis_version=analysis_version,
                    run_id=run_id,
                    model_used=model_name,
                    attempt_count=total_attempts,
                    prompt_version=prompt_version,
                )
                try:
                    structured = self.llm_client.generate_structured(
                        system_prompt=prompt,
                        user_payload=payload,
                        model=model_name,
                        timeout_seconds=config.timeout_seconds,
                    )
                    validated = self._validate_payload(
                        model_class,
                        structured,
                        metadata,
                    )
                    return _AgentAttemptResult(
                        agent_type=config.name,
                        status=self._status_for_payload(config.name, validated),
                        metadata=metadata,
                        payload=validated,
                    )
                except Exception as exc:
                    last_error = exc

        final_metadata = self._metadata(
            config=config,
            document=document,
            analysis_version=analysis_version,
            run_id=run_id,
            model_used=models_to_try[-1],
            attempt_count=total_attempts,
            prompt_version=prompt_version,
        )
        return _AgentAttemptResult(
            agent_type=config.name,
            status="error",
            metadata=final_metadata,
            error_type=type(last_error).__name__ if last_error else "agent_execution_error",
            error_text=str(last_error) if last_error else "unknown agent execution error",
        )

    def _metadata(
        self,
        *,
        config: AgentConfig,
        document: HydratedParsedDocument,
        analysis_version: str,
        run_id: int,
        model_used: str,
        attempt_count: int,
        prompt_version: str,
    ) -> AgentExecutionMetadata:
        return AgentExecutionMetadata(
            research_id=document.research_id,
            document_hash=document.document_hash or "",
            analysis_version=analysis_version,
            agent_type=config.name,
            model_requested=config.model,
            model_used=model_used,
            prompt_path=config.prompt_path,
            prompt_version=prompt_version,
            run_id=run_id,
            attempt_count=attempt_count,
            analyzed_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _validate_payload(
        model_class: type[BaseModel],
        payload: dict[str, object],
        metadata: AgentExecutionMetadata,
    ) -> BaseModel:
        full_payload = dict(payload)
        full_payload["metadata"] = AgentExecutor._model_dump(metadata)
        validator = getattr(model_class, "model_validate", None)
        if callable(validator):
            return validator(full_payload)
        return model_class.parse_obj(full_payload)

    @staticmethod
    def _status_for_payload(agent_type: str, payload: BaseModel) -> str:
        data = AgentExecutor._model_dump(payload)
        if agent_type == "trading_opportunities":
            return "success" if data.get("opportunities") else "no_output"
        if agent_type == "short_time_horizon":
            return "success" if data.get("insights") else "no_output"
        if agent_type == "talking_points":
            return "success" if data.get("talking_points") else "no_output"
        return "success"

    @staticmethod
    def _model_dump(model: BaseModel) -> dict[str, Any]:
        dumper = getattr(model, "model_dump", None)
        if callable(dumper):
            return dumper()
        return model.dict()
