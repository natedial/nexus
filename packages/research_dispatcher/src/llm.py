"""Unified LLM client supporting Anthropic, OpenAI, and compatible providers."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
import re
import time

import logging
import yaml

# Default config path
CONFIG_PATH = Path(__file__).parent.parent / "config" / "models.yaml"
logger = logging.getLogger(__name__)


@dataclass
class ExtendedThinking:
    """Extended thinking configuration."""

    enabled: bool = False
    budget_tokens: int = 10000


@dataclass
class ModelConfig:
    """Configuration for a single model."""

    provider: Literal["anthropic", "openai", "deepinfra", "openrouter"]
    model: str
    max_tokens: int = 16000
    temperature: float = 0
    request_timeout_seconds: float | None = 60.0
    max_retries: int = 0
    retry_backoff_seconds: float = 2.0
    response_format: dict[str, Any] | None = None
    drop_response_format_on_retry: bool = False
    tool_choice: str | None = None
    reasoning_effort: str | None = None
    prompt_profile: Literal["full", "lean", "minimal"] = "full"
    throughline_count: int = 0
    max_key_insight_words: int = 0
    max_supporting_themes: int = 0
    max_supporting_trades: int = 0
    payload_theme_limit: int = 0
    payload_trade_limit: int = 0
    extended_thinking: ExtendedThinking | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        """Create ModelConfig from dictionary."""
        thinking_data = data.get("extended_thinking", {})
        thinking = ExtendedThinking(
            enabled=thinking_data.get("enabled", False),
            budget_tokens=thinking_data.get("budget_tokens", 10000),
        ) if thinking_data else None

        return cls(
            provider=data["provider"],
            model=data["model"],
            max_tokens=data.get("max_tokens", 16000),
            temperature=data.get("temperature", 0),
            request_timeout_seconds=data.get("request_timeout_seconds", 60.0),
            max_retries=data.get("max_retries", 0),
            retry_backoff_seconds=data.get("retry_backoff_seconds", 2.0),
            response_format=data.get("response_format"),
            drop_response_format_on_retry=data.get("drop_response_format_on_retry", False),
            tool_choice=data.get("tool_choice"),
            reasoning_effort=data.get("reasoning_effort"),
            prompt_profile=data.get("prompt_profile", "full"),
            throughline_count=data.get("throughline_count", 0),
            max_key_insight_words=data.get("max_key_insight_words", 0),
            max_supporting_themes=data.get("max_supporting_themes", 0),
            max_supporting_trades=data.get("max_supporting_trades", 0),
            payload_theme_limit=data.get("payload_theme_limit", 0),
            payload_trade_limit=data.get("payload_trade_limit", 0),
            extended_thinking=thinking,
        )


@lru_cache(maxsize=1)
def load_model_config(config_path: Path | None = None) -> ModelConfig:
    """Load synthesis model configuration from YAML file."""
    path = config_path or CONFIG_PATH
    logger.info("Loading model config from %s", path)

    with open(path) as f:
        data = yaml.safe_load(f)

    config = ModelConfig.from_dict(data["synthesis"])

    if config.provider != "anthropic":
        if config.extended_thinking is not None:
            logger.warning(
                "Extended thinking is only supported for Anthropic; disabling."
            )
        config.extended_thinking = None
        return config

    if config.extended_thinking and config.extended_thinking.enabled:
        available = data.get("available_models", {}).get("anthropic", [])
        thinking_models = {
            entry.get("id")
            for entry in available
            if entry.get("supports_thinking") is True
        }
        if thinking_models and config.model not in thinking_models:
            raise ValueError(
                "Extended thinking is enabled but the selected model does not support it."
            )

    return config


def reload_model_config(config_path: Path | None = None) -> ModelConfig:
    """Reload model configuration (clears cache)."""
    load_model_config.cache_clear()
    return load_model_config(config_path)


def _load_config_data(config_path: Path | None = None) -> dict:
    """Load the raw YAML config once for model lookup helpers."""
    path = config_path or CONFIG_PATH
    with open(path) as f:
        return yaml.safe_load(f)


def load_skill_config(skill_name: str, config_path: Path | None = None) -> ModelConfig:
    """
    Load model configuration for a specific skill.

    Args:
        skill_name: Name of the skill (e.g., 'throughline_synthesizer', 'callout_extractor')
        config_path: Optional path to config file

    Returns:
        ModelConfig for the skill, or falls back to synthesis config if not defined
    """
    data = _load_config_data(config_path)
    skills = data.get("skills", {})
    skill_data = skills.get(skill_name)

    if not skill_data:
        logger.warning("Skill config not found for %s, using synthesis config", skill_name)
        return load_model_config(config_path)

    config = ModelConfig.from_dict(skill_data)

    # Validate extended thinking for non-Anthropic
    if config.provider != "anthropic" and config.extended_thinking:
        logger.warning("Extended thinking only supported for Anthropic; disabling for skill %s", skill_name)
        config.extended_thinking = None

    return config


def load_optional_skill_config(
    skill_name: str,
    config_path: Path | None = None,
) -> ModelConfig | None:
    """Load an optional skill config, returning None if it is not defined."""
    data = _load_config_data(config_path)
    skills = data.get("skills", {})
    skill_data = skills.get(skill_name)
    if not skill_data:
        return None

    config = ModelConfig.from_dict(skill_data)
    if config.provider != "anthropic" and config.extended_thinking:
        logger.warning(
            "Extended thinking only supported for Anthropic; disabling for skill %s",
            skill_name,
        )
        config.extended_thinking = None
    return config


class LLMClient:
    """Unified client for Anthropic, OpenAI, and compatible providers."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        deepinfra_api_key: str | None = None,
        openrouter_api_key: str | None = None,
    ):
        self._anthropic_client = None
        self._openai_client = None
        self._deepinfra_client = None
        self._openrouter_client = None
        self._anthropic_api_key = anthropic_api_key
        self._openai_api_key = openai_api_key
        self._deepinfra_api_key = deepinfra_api_key
        self._openrouter_api_key = openrouter_api_key

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

    @property
    def deepinfra(self):
        """Lazy-load DeepInfra's OpenAI-compatible client."""
        if self._deepinfra_client is None:
            import openai
            if not self._deepinfra_api_key:
                raise ValueError("DEEPINFRA_API_KEY is required when provider='deepinfra'")
            self._deepinfra_client = openai.OpenAI(
                api_key=self._deepinfra_api_key,
                base_url="https://api.deepinfra.com/v1/openai",
            )
        return self._deepinfra_client

    @property
    def openrouter(self):
        """Lazy-load OpenRouter's OpenAI-compatible client."""
        if self._openrouter_client is None:
            import openai
            if not self._openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY is required when provider='openrouter'")
            self._openrouter_client = openai.OpenAI(
                api_key=self._openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )
        return self._openrouter_client

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
        attempts = max(config.max_retries, 0) + 1

        for attempt in range(1, attempts + 1):
            try:
                if config.provider == "anthropic":
                    return self._generate_anthropic(config, system, user)
                if config.provider == "openai":
                    return self._generate_openai(config, system, user)
                if config.provider == "deepinfra":
                    return self._generate_deepinfra(config, system, user)
                if config.provider == "openrouter":
                    return self._generate_openrouter(config, system, user)
                raise ValueError(f"Unknown provider: {config.provider}")
            except Exception as exc:
                if attempt >= attempts:
                    raise
                logger.warning(
                    "LLM call failed for %s/%s on attempt %d/%d: %s",
                    config.provider,
                    config.model,
                    attempt,
                    attempts,
                    exc,
                )
                time.sleep(max(config.retry_backoff_seconds, 0))

    def _generate_anthropic(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """Generate completion using Anthropic."""
        thinking_enabled = config.extended_thinking and config.extended_thinking.enabled
        logger.info("Calling %s (thinking=%s)", config.model, thinking_enabled)

        kwargs = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        # Add extended thinking if enabled
        if thinking_enabled:
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
        logger.info("Calling %s", config.model)

        # Check if this is a reasoning model (o1, o1-mini)
        is_reasoning_model = config.model.startswith("o1")
        is_gpt5_family = config.model.startswith("gpt-5")
        uses_max_completion_tokens = config.model.startswith(("o1", "gpt-5"))

        if is_reasoning_model:
            # o1 models don't support system messages or temperature
            combined_message = f"{system}\n\n---\n\n{user}"
            response = self.openai.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": combined_message}],
                max_completion_tokens=config.max_tokens,
                timeout=config.request_timeout_seconds,
            )
        else:
            request = self._build_openai_compatible_request(config, system, user)
            if not is_gpt5_family:
                request["temperature"] = config.temperature
            if uses_max_completion_tokens:
                request["max_completion_tokens"] = config.max_tokens
            else:
                request["max_tokens"] = config.max_tokens
            response = self.openai.chat.completions.create(**request)

        return self._extract_openai_compatible_text(response.choices[0].message)

    def _generate_deepinfra(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """Generate completion using DeepInfra's OpenAI-compatible API."""
        logger.info("Calling %s via DeepInfra", config.model)

        last_error: Exception | None = None

        for variant_index, request in enumerate(
            self._build_deepinfra_request_variants(config, system, user),
            start=1,
        ):
            try:
                response = self.deepinfra.chat.completions.create(**request)
                return self._extract_openai_compatible_text(response.choices[0].message)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "DeepInfra request variant %d failed for %s: %s",
                    variant_index,
                    config.model,
                    exc,
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"No DeepInfra request variants built for {config.model}")

    def _generate_openrouter(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> str:
        """Generate completion using OpenRouter's OpenAI-compatible API."""
        logger.info("Calling %s via OpenRouter", config.model)
        request = self._build_openai_compatible_request(config, system, user)
        request["temperature"] = config.temperature
        request["max_tokens"] = config.max_tokens

        try:
            response = self.openrouter.chat.completions.create(**request)
        except Exception:
            if not config.drop_response_format_on_retry or "response_format" not in request:
                raise
            retry_request = dict(request)
            retry_request.pop("response_format", None)
            response = self.openrouter.chat.completions.create(**retry_request)

        return self._extract_openai_compatible_text(response.choices[0].message)

    def _build_openai_compatible_request(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> dict[str, Any]:
        """Build a request payload shared by OpenAI-compatible chat APIs."""
        request: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "timeout": config.request_timeout_seconds,
        }

        if config.response_format:
            request["response_format"] = config.response_format
        if config.tool_choice:
            request["tool_choice"] = config.tool_choice
        if config.reasoning_effort:
            request["reasoning_effort"] = config.reasoning_effort

        return request

    def _build_deepinfra_request_variants(
        self,
        config: ModelConfig,
        system: str,
        user: str,
    ) -> list[dict[str, Any]]:
        """Build DeepInfra request variants with model-specific compatibility defaults."""
        request = self._build_openai_compatible_request(config, system, user)
        request["temperature"] = config.temperature
        request["max_tokens"] = config.max_tokens

        if self._deepinfra_prefers_agentic_compat_flags(config.model):
            request.setdefault("tool_choice", "none")
            request.setdefault("reasoning_effort", "none")
            request.setdefault("response_format", {"type": "json_object"})

        variants = [request]

        if config.drop_response_format_on_retry and "response_format" in request:
            retry_request = dict(request)
            retry_request.pop("response_format", None)
            variants.append(retry_request)

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for variant in variants:
            fingerprint = tuple(
                sorted((key, repr(value)) for key, value in variant.items())
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduped.append(variant)

        return deduped

    def _deepinfra_prefers_agentic_compat_flags(self, model: str) -> bool:
        """Return True for DeepInfra models that behave more reliably with agentic-safe defaults."""
        normalized = model.lower()
        if "kimi-k2.5" in normalized and "instruct" not in normalized:
            return True
        if "minimax-m2.5" in normalized and "instruct" not in normalized:
            return True
        return False

    def _extract_openai_compatible_text(self, message) -> str:
        """Extract text from OpenAI-compatible message objects and strip reasoning wrappers."""
        content = getattr(message, "content", "") or ""

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(item["text"])
                elif getattr(item, "type", None) == "text" and getattr(item, "text", None):
                    parts.append(item.text)
            content = "".join(parts)

        text = str(content).strip()
        if not text:
            return ""

        if "</think>" in text:
            text = text.rsplit("</think>", 1)[-1].strip()
        else:
            text = re.sub(r"(?s)^<think>.*?</think>\s*", "", text).strip()
            if text.startswith("<think>"):
                logger.warning("Model response contained only an unterminated <think> block.")
                return ""

        return text
