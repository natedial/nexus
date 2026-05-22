"""Helpers for structured extraction with validation-aware provider fallback."""

import json
from collections.abc import Callable
from typing import TypeVar

import structlog

from src.llm import LLMClient, ModelConfig

T = TypeVar("T")


def generate_with_validation_fallback(
    client: LLMClient,
    config: ModelConfig,
    system: str,
    user: str,
    parser: Callable[[str], T],
    log: structlog.stdlib.BoundLogger | structlog.stdlib.BoundLoggerBase,
    step: str,
    response_format: dict | None = None,
) -> T:
    """Try each configured provider until generation and parsing both succeed."""
    attempts = (
        client.model_attempts(config)
        if hasattr(client, "model_attempts")
        else LLMClient.model_attempts(config)
    )
    last_error: Exception | None = None

    for idx, attempt in enumerate(attempts, start=1):
        raw = ""
        if idx > 1:
            log.info(
                "Retrying structured extraction with fallback model",
                step=step,
                attempt=idx,
                total_attempts=len(attempts),
                provider=attempt.provider,
                model=attempt.model,
            )
        try:
            if hasattr(client, "generate_once"):
                raw = client.generate_once(
                    config=attempt,
                    system=system,
                    user=user,
                    response_format=response_format,
                )
            else:
                raw = client.generate(
                    config=attempt,
                    system=system,
                    user=user,
                    response_format=response_format,
                )
            return parser(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            log.warning(
                "Structured extraction output invalid",
                step=step,
                attempt=idx,
                total_attempts=len(attempts),
                provider=attempt.provider,
                model=attempt.model,
                error=str(exc),
                raw=raw[:500],
            )
        except Exception as exc:
            last_error = exc
            log.warning(
                "Structured extraction generation failed",
                step=step,
                attempt=idx,
                total_attempts=len(attempts),
                provider=attempt.provider,
                model=attempt.model,
                error=str(exc),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No model attempts were configured for {step}")
