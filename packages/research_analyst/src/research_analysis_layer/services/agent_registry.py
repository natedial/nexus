"""Agent registry and configuration loader."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from research_analysis_layer.services.round_executor import RoundConfig

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = Path(os.getenv("RESEARCH_PROCESSING_ROOT", REPO_ROOT.parent))


@dataclass
class AgentConfig:
    """Configuration for a single analysis agent."""

    name: str
    prompt_path: str
    model: str
    fallback_model: str
    timeout_seconds: int
    retry_count: int
    priority: int
    table_name: str
    tools: list[str] = None
    max_tool_calls: int = 0
    output_schema: str = ""
    temperature: float = 0.4


class AgentRegistry:
    """Registry for managing analysis agents."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or self._default_config_path()
        self._agents: dict[str, AgentConfig] = {}
        self._rounds: list[RoundConfig] = []
        self._default_model: str = "claude-haiku-4-20250514"
        self._default_timeout: int = 60
        self._default_retry_count: int = 3
        self._load_config()

    def _default_config_path(self) -> Path:
        """Find the default config file."""
        candidates = [
            REPO_ROOT / "agent_config.yaml",
            WORKSPACE_ROOT / "research_analyst" / "agent_config.yaml",
            WORKSPACE_ROOT / "agent_config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _load_config(self) -> None:
        """Load agent configuration from YAML file."""
        if not self.config_path.exists():
            logger.warning(
                "Agent config not found at %s, using empty registry",
                self.config_path,
            )
            return

        with open(self.config_path) as f:
            data = yaml.safe_load(f)

        if not data:
            return

        self._default_model = data.get("default_model", self._default_model)
        self._default_timeout = data.get(
            "default_timeout_seconds", self._default_timeout
        )
        self._default_retry_count = data.get(
            "default_retry_count", self._default_retry_count
        )

        agents_data = data.get("agents", {})
        for name, config in agents_data.items():
            model_config = config.get("model", {})
            if isinstance(model_config, dict):
                model = model_config.get("primary", self._default_model)
                fallback_model = model_config.get("fallback", self._default_model)
            else:
                model = model_config if model_config else self._default_model
                fallback_model = config.get("fallback_model", self._default_model)

            self._agents[name] = AgentConfig(
                name=name,
                prompt_path=config.get("prompt_path", config.get("prompt", "")),
                model=model,
                fallback_model=fallback_model,
                timeout_seconds=config.get("timeout_seconds", self._default_timeout),
                retry_count=config.get("retry_count", self._default_retry_count),
                priority=config.get("priority", 99),
                table_name=config.get("table_name", f"{name}_analysis"),
                tools=config.get("tools", []),
                max_tool_calls=config.get("max_tool_calls", 0),
                output_schema=config.get("output_schema", ""),
                temperature=config.get("temperature", 0.4),
            )

        rounds_data = data.get("rounds", [])
        if rounds_data:
            from research_analysis_layer.services.round_executor import RoundConfig

            for round_data in rounds_data:
                self._rounds.append(
                    RoundConfig(
                        name=round_data.get("name", ""),
                        type=round_data.get("type", "parallel"),
                        agents=round_data.get("agents", []),
                        receives=round_data.get("receives", ["input"]),
                        fail_round_on_agent_error=round_data.get(
                            "fail_round_on_agent_error", False
                        ),
                    )
                )

        logger.info(
            "Loaded agent config: agent_count=%s config_path=%s",
            len(self._agents),
            self.config_path,
        )

    def get_agent(self, name: str) -> AgentConfig | None:
        """Get agent configuration by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[AgentConfig]:
        """List all registered agents sorted by priority."""
        return sorted(self._agents.values(), key=lambda a: a.priority)

    def get_agent_names(self) -> list[str]:
        """Get list of agent names."""
        return list(self._agents.keys())

    def resolve_prompt_path(self, agent_name: str) -> Path | None:
        """Resolve the full path to an agent's prompt file."""
        agent = self._agents.get(agent_name)
        if not agent:
            return None

        prompt_path = Path(agent.prompt_path)
        candidates = []
        if prompt_path.is_absolute():
            candidates.append(prompt_path)
        else:
            candidates.append(self.config_path.parent / prompt_path)
            candidates.append(WORKSPACE_ROOT / prompt_path)
            candidates.append(REPO_ROOT / prompt_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        logger.warning(
            "Prompt file not found for agent %s: %s",
            agent_name,
            candidates[0] if candidates else prompt_path,
        )
        return None

    def load_prompt(self, agent_name: str) -> str | None:
        """Load the prompt content for an agent."""
        path = self.resolve_prompt_path(agent_name)
        if not path:
            return None
        return path.read_text().strip()

    def get_table_name(self, agent_name: str) -> str | None:
        """Get the Supabase table name for an agent."""
        agent = self._agents.get(agent_name)
        return agent.table_name if agent else None

    @property
    def default_model(self) -> str:
        """Get the default model for agents without specific config."""
        return self._default_model

    def get_rounds(self) -> list:
        """Get the round configurations."""
        return self._rounds

    def has_rounds_config(self) -> bool:
        """Check if rounds config is loaded."""
        return len(self._rounds) > 0


# Global registry instance
_registry: AgentRegistry | None = None


def get_registry(config_path: Path | None = None) -> AgentRegistry:
    """Get or create the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry(config_path)
    return _registry


def reset_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _registry
    _registry = None
