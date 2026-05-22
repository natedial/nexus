"""Unified LLM client supporting Anthropic, OpenAI, and compatible providers."""

from dataclasses import dataclass, replace
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

    provider: Literal[
        "anthropic",
        "openai",
        "groq",
        "deepinfra",
        "openrouter",
        "fireworks",
        "together",
    ]
    model: str
    max_tokens: int = 4096
    temperature: float = 0
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    extended_thinking: ExtendedThinking | None = None
    fallback: list["ModelConfig"] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        """Create ModelConfig from dictionary."""
        thinking_data = data.get("extended_thinking", {})
        thinking = ExtendedThinking(
            enabled=thinking_data.get("enabled", False),
            budget_tokens=thinking_data.get("budget_tokens", 8000),
        ) if thinking_data else None
        fallback_data = data.get("fallback", [])
        fallback = [cls.from_dict(item) for item in fallback_data] if fallback_data else None

        return cls(
            provider=data["provider"],
            model=data["model"],
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0),
            reasoning_effort=data.get("reasoning_effort"),
            extended_thinking=thinking,
            fallback=fallback,
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

    def _validate_entry(step: str, config: dict, path: str = "primary") -> None:
        provider = config.get("provider")
        model = config.get("model")
        if not provider or not model:
            return
        if provider in available_ids and model not in available_ids[provider]:
            logger.warning(
                "Configured model not listed in available_models",
                step=step,
                config_path=path,
                provider=provider,
                model=model,
            )
        for idx, fallback in enumerate(config.get("fallback") or []):
            _validate_entry(step, fallback, path=f"{path}.fallback[{idx}]")

    for step, config in extraction.items():
        _validate_entry(step, config)


def reload_model_config(config_path: Path | None = None) -> ExtractionConfig:
    """Reload model configuration (clears cache)."""
    load_model_config.cache_clear()
    return load_model_config(config_path)


class LLMClient:
    """Unified client for Anthropic, OpenAI, and OpenAI-compatible providers."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        groq_api_key: str | None = None,
        deepinfra_api_key: str | None = None,
        openrouter_api_key: str | None = None,
        fireworks_api_key: str | None = None,
        together_api_key: str | None = None,
        request_timeout_s: float = 120.0,
    ):
        self._anthropic_client = None
        self._openai_client = None
        self._groq_client = None
        self._deepinfra_client = None
        self._openrouter_client = None
        self._fireworks_client = None
        self._together_client = None
        self._anthropic_api_key = anthropic_api_key
        self._openai_api_key = openai_api_key
        self._groq_api_key = groq_api_key
        self._deepinfra_api_key = deepinfra_api_key
        self._openrouter_api_key = openrouter_api_key
        self._fireworks_api_key = fireworks_api_key
        self._together_api_key = together_api_key
        self._request_timeout_s = request_timeout_s

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
                api_key=self._openai_api_key,
                timeout=self._request_timeout_s,
            )
        return self._openai_client

    @property
    def groq(self):
        """Lazy-load Groq client (OpenAI-compatible API)."""
        if self._groq_client is None:
            import openai
            if not self._groq_api_key:
                raise ValueError("GROQ_API_KEY is required when provider='groq'")
            self._groq_client = openai.OpenAI(
                api_key=self._groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                timeout=self._request_timeout_s,
            )
        return self._groq_client

    @property
    def deepinfra(self):
        """Lazy-load DeepInfra client (OpenAI-compatible API)."""
        if self._deepinfra_client is None:
            import openai
            if not self._deepinfra_api_key:
                raise ValueError("DEEPINFRA_API_KEY is required when provider='deepinfra'")
            self._deepinfra_client = openai.OpenAI(
                api_key=self._deepinfra_api_key,
                base_url="https://api.deepinfra.com/v1/openai",
                timeout=self._request_timeout_s,
            )
        return self._deepinfra_client

    @property
    def openrouter(self):
        """Lazy-load OpenRouter client (OpenAI-compatible API)."""
        if self._openrouter_client is None:
            import openai
            if not self._openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY is required when provider='openrouter'")
            self._openrouter_client = openai.OpenAI(
                api_key=self._openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                timeout=self._request_timeout_s,
            )
        return self._openrouter_client

    @property
    def fireworks(self):
        """Lazy-load Fireworks client (OpenAI-compatible API)."""
        if self._fireworks_client is None:
            import openai
            if not self._fireworks_api_key:
                raise ValueError("FIREWORKS_API_KEY is required when provider='fireworks'")
            self._fireworks_client = openai.OpenAI(
                api_key=self._fireworks_api_key,
                base_url="https://api.fireworks.ai/inference/v1",
                timeout=self._request_timeout_s,
            )
        return self._fireworks_client

    @property
    def together(self):
        """Lazy-load Together client (OpenAI-compatible API)."""
        if self._together_client is None:
            import openai
            if not self._together_api_key:
                raise ValueError("TOGETHER_API_KEY is required when provider='together'")
            self._together_client = openai.OpenAI(
                api_key=self._together_api_key,
                base_url="https://api.together.xyz/v1",
                timeout=self._request_timeout_s,
            )
        return self._together_client

    def _openai_compatible_client(self, provider: str):
        """Return an OpenAI-compatible client for non-OpenAI providers."""
        if provider == "groq":
            return self.groq
        if provider == "deepinfra":
            return self.deepinfra
        if provider == "openrouter":
            return self.openrouter
        if provider == "fireworks":
            return self.fireworks
        if provider == "together":
            return self.together
        raise ValueError(f"Unsupported OpenAI-compatible provider: {provider}")

    @staticmethod
    def _is_deepinfra_agentic_model(config: ModelConfig) -> bool:
        if config.provider != "deepinfra":
            return False
        model = config.model.lower()
        return model.startswith("minimaxai/") or model == "moonshotai/kimi-k2.5"

    def _openai_compatible_request_kwargs(
        self,
        config: ModelConfig,
        system: str,
        user: str,
        response_format: dict | None = None,
    ) -> dict:
        """Build provider-specific kwargs for OpenAI-compatible chat completions."""
        request_format = response_format
        kwargs = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }
        if self._is_deepinfra_agentic_model(config):
            kwargs["tool_choice"] = "none"
            kwargs["reasoning_effort"] = "none"
            if request_format is not None:
                request_format = {"type": "json_object"}
        elif config.reasoning_effort is not None and config.provider == "openrouter":
            kwargs["extra_body"] = {
                "reasoning": {
                    "effort": config.reasoning_effort,
                    "exclude": True,
                }
            }
        if request_format is not None:
            kwargs["response_format"] = request_format
        return kwargs

    @staticmethod
    def model_attempts(config: ModelConfig) -> list[ModelConfig]:
        """Return the configured provider chain without nested fallback lists."""
        attempts = [replace(config, fallback=None)]
        attempts.extend(replace(item, fallback=None) for item in (config.fallback or []))
        return attempts

    def generate_once(
        self,
        config: ModelConfig,
        system: str,
        user: str,
        response_format: dict | None = None,
    ) -> str:
        """Generate a completion using exactly one provider/model config."""
        result = self._generate_single(
            config=config,
            system=system,
            user=user,
            response_format=response_format,
        )
        if not result or not result.strip():
            raise RuntimeError("Empty model response")
        return result

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
        attempts = self.model_attempts(config)
        last_error: Exception | None = None

        for idx, attempt in enumerate(attempts, start=1):
            try:
                if idx > 1:
                    logger.info(
                        "Retrying generation with fallback model",
                        attempt=idx,
                        total_attempts=len(attempts),
                        provider=attempt.provider,
                        model=attempt.model,
                    )
                result = self.generate_once(
                    config=attempt,
                    system=system,
                    user=user,
                    response_format=response_format,
                )
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    "Generation attempt failed",
                    attempt=idx,
                    total_attempts=len(attempts),
                    provider=attempt.provider,
                    model=attempt.model,
                    error=str(e),
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("No model attempts were configured")

    def _generate_single(
        self,
        config: ModelConfig,
        system: str,
        user: str,
        response_format: dict | None = None,
    ) -> str:
        """Generate a completion with one provider/model configuration."""
        if config.provider == "anthropic":
            return self._generate_anthropic(config, system, user)
        elif config.provider == "openai":
            return self._generate_openai(config, system, user, response_format=response_format)
        elif config.provider in ("groq", "deepinfra", "openrouter", "fireworks", "together"):
            return self._generate_openai_compatible(
                config,
                system,
                user,
                response_format=response_format,
            )
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
            thinking_enabled=(
                config.extended_thinking.enabled if config.extended_thinking else False
            ),
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
            reasoning_effort=config.reasoning_effort,
        )

        import openai

        if config.model.startswith("gpt-5") or config.reasoning_effort is not None:
            if response_format is not None and config.reasoning_effort is None:
                try:
                    kwargs = {
                        "model": config.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_completion_tokens": config.max_tokens,
                        "temperature": config.temperature,
                        "response_format": response_format,
                    }
                    if config.reasoning_effort is not None:
                        kwargs["reasoning_effort"] = config.reasoning_effort
                    response = self.openai.chat.completions.create(**kwargs)
                    return response.choices[0].message.content or ""
                except (openai.BadRequestError, TypeError) as e:
                    logger.warning(
                        "OpenAI chat.completions rejected response_format for gpt-5, "
                        "retrying with responses",
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

    def _generate_openai_compatible(
        self,
        config: ModelConfig,
        system: str,
        user: str,
        response_format: dict | None = None,
    ) -> str:
        """Generate completion using an OpenAI-compatible provider."""
        if response_format is not None and "json" not in system.lower():
            system = f"{system}\n\nRespond with valid json only."
        logger.debug(
            "Calling OpenAI-compatible provider",
            provider=config.provider,
            model=config.model,
            max_tokens=config.max_tokens,
            reasoning_effort=config.reasoning_effort,
        )

        client = self._openai_compatible_client(config.provider)
        kwargs = self._openai_compatible_request_kwargs(
            config,
            system,
            user,
            response_format=response_format,
        )

        try:
            response = client.chat.completions.create(**kwargs)
        except TypeError as e:
            logger.warning(
                "OpenAI-compatible provider rejected response_format, retrying without it",
                provider=config.provider,
                model=config.model,
                error=str(e),
            )
            kwargs.pop("response_format", None)
            if "reasoning_effort" in kwargs and not self._is_deepinfra_agentic_model(config):
                kwargs.pop("reasoning_effort", None)
            kwargs.pop("extra_body", None)
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            if (
                response_format is None
                and "reasoning_effort" not in kwargs
                and "extra_body" not in kwargs
            ):
                raise
            if "extra_body" in kwargs:
                logger.warning(
                    "OpenAI-compatible provider rejected reasoning payload, retrying without it",
                    provider=config.provider,
                    model=config.model,
                    error=str(e),
                )
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("extra_body", None)
                try:
                    response = client.chat.completions.create(**retry_kwargs)
                    return response.choices[0].message.content or ""
                except Exception as retry_error:
                    logger.warning(
                        "OpenAI-compatible provider rejected structured compatibility payload",
                        provider=config.provider,
                        model=config.model,
                        error=str(retry_error),
                    )
                    kwargs = retry_kwargs
            logger.warning(
                "OpenAI-compatible provider request rejected, retrying with compatibility payload",
                provider=config.provider,
                model=config.model,
                error=str(e),
            )
            kwargs.pop("response_format", None)
            if "reasoning_effort" in kwargs and not self._is_deepinfra_agentic_model(config):
                kwargs.pop("reasoning_effort", None)
            kwargs.pop("extra_body", None)
            response = client.chat.completions.create(**kwargs)

        return response.choices[0].message.content or ""

    @staticmethod
    def _responses_text_config(response_format: dict | None) -> dict | None:
        """Convert Chat Completions response_format into Responses API text config."""
        if response_format is None:
            return None

        if response_format.get("type") == "json_schema" and "json_schema" in response_format:
            schema_config = {
                "type": "json_schema",
                **response_format["json_schema"],
            }
            return {"format": schema_config}

        return {"format": response_format}

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
            reasoning = (
                {"effort": config.reasoning_effort}
                if config.reasoning_effort is not None
                else None
            )
            kwargs = {
                "model": config.model,
                "input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_output_tokens": config.max_tokens,
            }
            if reasoning is not None:
                kwargs["reasoning"] = reasoning
            else:
                kwargs["temperature"] = config.temperature
            text_config = self._responses_text_config(response_format)
            if text_config is not None:
                kwargs["text"] = text_config
            response = self.openai.responses.create(
                **kwargs,
            )
        except TypeError as e:
            logger.warning(
                "OpenAI responses rejected structured text format, retrying without it",
                model=config.model,
                error=str(e),
            )
            kwargs.pop("text", None)
            response = self.openai.responses.create(
                **kwargs,
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
            content = (
                item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            )
            for block in content or []:
                block_type = (
                    block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                )
                if block_type not in ("output_text", "text"):
                    continue
                text = (
                    block.get("text")
                    if isinstance(block, dict)
                    else getattr(block, "text", None)
                )
                if text:
                    parts.append(text)

        return "\n".join(parts)
