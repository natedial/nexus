"""Second-provider clients, so a debate panel can span model families."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from research_analysis_layer.env import load_env_files
from research_analysis_layer.services.agent_registry import AgentRegistry
from research_analysis_layer.services.model_family import model_family

logger = logging.getLogger(__name__)

_JUDGE_EFFORT = "medium"


def _build_anthropic(models: list[str]) -> Any | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    from research_analysis_layer.evals.decision_agent_anthropic import (
        AnthropicReferenceClient,
    )

    return AnthropicReferenceClient(
        api_key=api_key,
        sampling_by_model={model: {"effort": _JUDGE_EFFORT} for model in models},
    )


PROVIDER_BUILDERS: dict[str, Callable[[list[str]], Any | None]] = {
    "anthropic": _build_anthropic,
}


@dataclass(frozen=True)
class PanelDescription:
    """Which judges can run, and whether they span two model families."""

    judges: list[tuple[str, str | None]]
    unavailable: list[str]

    @property
    def independent(self) -> bool:
        return len({family for _, family in self.judges if family}) >= 2


def build_provider_clients(settings: Any, registry: AgentRegistry) -> dict[str, Any]:
    """Build a client for each extra provider the configured rounds name.

    Nothing is built while debate is off, so no second provider is contacted.
    """
    if settings.analyst_debate_mode == "off":
        return {}
    load_env_files()
    models: dict[str, list[str]] = {}
    for round_config in registry.get_rounds():
        for name in round_config.agents:
            agent = registry.get_agent(name)
            if agent is not None and agent.provider:
                models.setdefault(agent.provider, []).append(agent.model)
    clients: dict[str, Any] = {}
    for provider, names in models.items():
        builder = PROVIDER_BUILDERS.get(provider)
        client = builder(names) if builder is not None else None
        if client is None:
            logger.warning("Debate provider %s is not configured", provider)
            continue
        clients[provider] = client
    return clients


def describe_panel(
    registry: AgentRegistry,
    *,
    available_providers: set[str],
    judge_model: str | None = None,
) -> PanelDescription:
    judges: list[tuple[str, str | None]] = []
    unavailable: list[str] = []
    for round_config in registry.get_rounds():
        if round_config.name != "adjudication":
            continue
        for name in round_config.agents:
            agent = registry.get_agent(name)
            if agent is None or (
                agent.provider and agent.provider not in available_providers
            ):
                unavailable.append(name)
                continue
            model = judge_model if name == "adjudicator" and judge_model else agent.model
            judges.append((name, model_family(model)))
    return PanelDescription(judges=judges, unavailable=unavailable)
