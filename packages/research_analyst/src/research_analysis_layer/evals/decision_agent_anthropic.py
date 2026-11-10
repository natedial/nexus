"""Single-attempt Anthropic client for agent-reference judgments.

It satisfies the small part of the ``AgentLlmClient`` interface that
``StructuredJudgmentProvider`` uses. SDK retries are disabled
(``max_retries=0``) so the reference harness counts and bounds every attempt
itself. It deliberately does not enable refusal fallbacks: a fallback would
serve a different model than the pinned one, and the provider rejects that.
"""

from __future__ import annotations

from typing import Any, Mapping

from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
    _try_parse_json,
)

SUPPORTED_SAMPLING_KEYS = frozenset({"effort"})


class AnthropicReferenceClient:
    reference_calls_are_single_attempt = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        sampling_by_model: Mapping[str, Mapping[str, Any]] | None = None,
        max_output_tokens: int = 16_000,
        sdk_client: Any | None = None,
    ) -> None:
        self._sampling = {
            model: dict(sampling) for model, sampling in (sampling_by_model or {}).items()
        }
        for model, sampling in self._sampling.items():
            unknown = set(sampling) - SUPPORTED_SAMPLING_KEYS
            if unknown:
                raise ValueError(
                    f"Anthropic client cannot apply sampling keys {sorted(unknown)} "
                    f"for {model}"
                )
        self._max_output_tokens = max_output_tokens
        if sdk_client is None:
            import anthropic

            sdk_client = anthropic.Anthropic(api_key=api_key, max_retries=0)
        self._client = sdk_client

    def reference_sampling_for_model(self, model: str) -> dict[str, Any]:
        return dict(self._sampling.get(model, {}))

    def generate_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
        max_tool_calls: int = 0,
        timeout_seconds: int = 120,
    ) -> AgentCallResult:
        if tools or max_tool_calls:
            raise ValueError("reference judgments must not expose tools")
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_output_tokens,
            "system": system_prompt,
            "messages": messages,
            "timeout": float(timeout_seconds),
        }
        effort = self._sampling.get(model, {}).get("effort")
        if effort:
            kwargs["output_config"] = {"effort": effort}
        response = self._client.messages.create(**kwargs)
        raw_text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        usage = response.usage
        return AgentCallResult(
            raw_text=raw_text,
            parsed_output=_try_parse_json(raw_text),
            token_usage=TokenUsage(
                input_tokens=int(usage.input_tokens or 0),
                output_tokens=int(usage.output_tokens or 0),
                cache_read_input_tokens=int(
                    getattr(usage, "cache_read_input_tokens", 0) or 0
                ),
                cache_creation_input_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
            ),
            model_used=str(response.model or model),
            stop_reason=str(response.stop_reason or ""),
        )


__all__ = ["AnthropicReferenceClient"]
