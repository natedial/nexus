"""Unified LLM client supporting Anthropic and OpenAI."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import structlog
import yaml

logger = structlog.get_logger()

# Default config path
CONFIG_PATH = Path(__file__).parent.parent / "config" / "models.yaml"


@dataclass
class ExtendedThinking:
    """Extended thinking configuration."""

    enabled: bool = False
    budget_tokens: int = 8000


@dataclass
class ModelConfig:
    """Configuration for a single model."""

    provider: Literal["anthropic", "openai"]
    model: str
    max_tokens: int = 4096
    temperature: float = 0
    extended_thinking: ExtendedThinking | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        """Create ModelConfig from dictionary."""
        thinking_data = data.get("extended_thinking", {})
        thinking = ExtendedThinking(
            enabled=thinking_data.get("enabled", False),
            budget_tokens=thinking_data.get("budget_tokens", 8000),
        ) if thinking_data else None

        return cls(
            provider=data["provider"],
            model=data["model"],
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0),
            extended_thinking=thinking,
        )


@dataclass
class ExtractionConfig:
    """Configuration for all extraction steps.

    Note: Synthesis is performed downstream by research_dispatcher.
    """

    boilerplate: ModelConfig
    metadata: ModelConfig
    themes: ModelConfig
    trades: ModelConfig

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionConfig":
        """Create ExtractionConfig from dictionary."""
        return cls(
            boilerplate=ModelConfig.from_dict(data["boilerplate"]),
            metadata=ModelConfig.from_dict(data["metadata"]),
            themes=ModelConfig.from_dict(data["themes"]),
            trades=ModelConfig.from_dict(data["trades"]),
        )


@lru_cache(maxsize=1)
def load_model_config(config_path: Path | None = None) -> ExtractionConfig:
    """Load model configuration from YAML file."""
    path = config_path or CONFIG_PATH
    logger.info("Loading model config", path=str(path))

    with open(path) as f:
        data = yaml.safe_load(f)

    return ExtractionConfig.from_dict(data["extraction"])


def reload_model_config(config_path: Path | None = None) -> ExtractionConfig:
    """Reload model configuration (clears cache)."""
    load_model_config.cache_clear()
    return load_model_config(config_path)


class LLMClient:
    """Unified client for Anthropic and OpenAI."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
    ):
        self._anthropic_client = None
        self._openai_client = None
        self._anthropic_api_key = anthropic_api_key
        self._openai_api_key = openai_api_key

    @property
    def anthropic(self):
        """Lazy-load Anthropic client."""
        if self._anthropic_client is None:
            import anthropic
            self._anthropic_client = anthropic.Anthropic(
                api_key=self._anthropic_api_key
            )
        return self._anthropic_client

    @property
    def openai(self):
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            import openai
            self._openai_client = openai.OpenAI(
                api_key=self._openai_api_key
            )
        return self._openai_client

    def generate(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """
        Generate a completion using the configured provider/model.

        Args:
            config: Model configuration specifying provider, model, etc.
            system: System prompt
            user: User message content

        Returns:
            The generated text response
        """
        if config.provider == "anthropic":
            return self._generate_anthropic(config, system, user)
        elif config.provider == "openai":
            return self._generate_openai(config, system, user)
        else:
            raise ValueError(f"Unknown provider: {config.provider}")

    def _generate_anthropic(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """Generate completion using Anthropic."""
        logger.debug(
            "Calling Anthropic",
            model=config.model,
            max_tokens=config.max_tokens,
            thinking_enabled=config.extended_thinking.enabled if config.extended_thinking else False,
        )

        kwargs = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        # Add temperature if not using extended thinking
        # (extended thinking requires temperature=1)
        if config.extended_thinking and config.extended_thinking.enabled:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": config.extended_thinking.budget_tokens,
            }
        else:
            kwargs["temperature"] = config.temperature

        response = self.anthropic.messages.create(**kwargs)

        # Extract text, handling extended thinking blocks
        for block in response.content:
            if block.type == "text":
                return block.text

        return ""

    def _generate_openai(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """Generate completion using OpenAI."""
        logger.debug(
            "Calling OpenAI",
            model=config.model,
            max_tokens=config.max_tokens,
        )

        # Check if this is a reasoning model (o1, o1-mini)
        is_reasoning_model = config.model.startswith("o1")

        if is_reasoning_model:
            # o1 models don't support system messages or temperature
            # Prepend system prompt to user message
            combined_message = f"{system}\n\n---\n\n{user}"
            response = self.openai.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": combined_message}],
                max_completion_tokens=config.max_tokens,
            )
        else:
            response = self.openai.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=config.max_tokens,
                temperature=config.temperature,
            )

        return response.choices[0].message.content or ""
