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

    _validate_model_config(data)
    return ExtractionConfig.from_dict(data["extraction"])


def _validate_model_config(data: dict) -> None:
    """Warn if configured models aren't listed in available_models."""
    available = data.get("available_models")
    extraction = data.get("extraction")
    if not available or not extraction:
        return

    available_ids = {}
    for provider, models in available.items():
        available_ids[provider] = {m.get("id") for m in models if m.get("id")}

    for step, config in extraction.items():
        provider = config.get("provider")
        model = config.get("model")
        if not provider or not model:
            continue
        if provider in available_ids and model not in available_ids[provider]:
            logger.warning(
                "Configured model not listed in available_models",
                step=step,
                provider=provider,
                model=model,
            )


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
        response_format: dict | None = None,
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
            return self._generate_openai(config, system, user, response_format=response_format)
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
        response_format: dict | None = None,
    ) -> str:
        """Generate completion using OpenAI."""
        if response_format is not None and "json" not in system.lower():
            system = f"{system}\n\nRespond with valid json only."
        logger.debug(
            "Calling OpenAI",
            model=config.model,
            max_tokens=config.max_tokens,
        )

        import openai

        if config.model.startswith("gpt-5"):
            if response_format is not None:
                try:
                    response = self.openai.chat.completions.create(
                        model=config.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        max_completion_tokens=config.max_tokens,
                        temperature=config.temperature,
                        response_format=response_format,
                    )
                    return response.choices[0].message.content or ""
                except (openai.BadRequestError, TypeError) as e:
                    logger.warning(
                        "OpenAI chat.completions rejected response_format for gpt-5, retrying with responses",
                        model=config.model,
                        error=str(e),
                    )
            try:
                return self._generate_openai_responses(
                    config,
                    system,
                    user,
                    response_format=response_format,
                )
            except openai.BadRequestError as e:
                logger.warning(
                    "OpenAI responses request rejected, retrying with chat.completions",
                    model=config.model,
                    error=str(e),
                )

        # Check if this is a reasoning model (o1, o1-mini)
        is_reasoning_model = config.model.startswith("o1")

        try:
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
                if config.model.startswith("gpt-5"):
                    response = self.openai.chat.completions.create(
                        model=config.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        max_completion_tokens=config.max_tokens,
                        temperature=config.temperature,
                        response_format=response_format,
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
                        response_format=response_format,
                    )
        except openai.BadRequestError as e:
            logger.warning(
                "OpenAI request rejected, retrying with compatibility payload",
                model=config.model,
                error=str(e),
            )
            combined_message = f"{system}\n\n---\n\n{user}"
            response = self.openai.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": combined_message}],
                max_completion_tokens=config.max_tokens,
                response_format=response_format,
            )
        except TypeError as e:
            logger.warning(
                "OpenAI chat.completions rejected response_format, retrying without it",
                model=config.model,
                error=str(e),
            )
            if is_reasoning_model:
                combined_message = f"{system}\n\n---\n\n{user}"
                response = self.openai.chat.completions.create(
                    model=config.model,
                    messages=[{"role": "user", "content": combined_message}],
                    max_completion_tokens=config.max_tokens,
                )
            else:
                if config.model.startswith("gpt-5"):
                    response = self.openai.chat.completions.create(
                        model=config.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        max_completion_tokens=config.max_tokens,
                        temperature=config.temperature,
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

    def _generate_openai_responses(
        self,
        config: ModelConfig,
        system: str,
        user: str,
        response_format: dict | None = None,
    ) -> str:
        """Generate completion using OpenAI Responses API."""
        if response_format is not None and "json" not in system.lower():
            system = f"{system}\n\nRespond with valid json only."
        try:
            response = self.openai.responses.create(
                model=config.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_output_tokens=config.max_tokens,
                temperature=config.temperature,
                response_format=response_format,
            )
        except TypeError as e:
            logger.warning(
                "OpenAI responses rejected response_format, retrying without it",
                model=config.model,
                error=str(e),
            )
            response = self.openai.responses.create(
                model=config.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_output_tokens=config.max_tokens,
                temperature=config.temperature,
            )
        return self._extract_responses_text(response)

    @staticmethod
    def _extract_responses_text(response) -> str:
        """Extract text from an OpenAI Responses API result."""
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        output = getattr(response, "output", None) or []
        parts = []
        for item in output:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            for block in content or []:
                block_type = (
                    block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                )
                if block_type not in ("output_text", "text"):
                    continue
                text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
                if text:
                    parts.append(text)

        return "\n".join(parts)
