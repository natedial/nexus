"""LLM client boundary for analysis agents."""

from __future__ import annotations

import json
from typing import Protocol
import urllib.request

from research_analysis_layer.config import Settings


class AgentLlmClient(Protocol):
    """Protocol for provider-backed structured generation."""

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        model: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        """Return a JSON object parsed from the model response."""


class AnthropicAgentLlmClient:
    """Small Anthropic Messages API wrapper using stdlib HTTP."""

    def __init__(self, *, api_key: str, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        model: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        body = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                user_payload,
                                ensure_ascii=True,
                                sort_keys=True,
                            ),
                        }
                    ],
                }
            ],
        }
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return self._extract_json_object(data)

    @staticmethod
    def _extract_json_object(response: dict[str, object]) -> dict[str, object]:
        content = response.get("content")
        if not isinstance(content, list):
            raise ValueError("anthropic response missing content list")
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
        raw = "\n".join(text_parts).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("structured response must be a JSON object")
        return parsed


def build_agent_llm_client(settings: Settings) -> AgentLlmClient | None:
    """Construct the configured agent LLM client."""

    if not settings.agent_execution_enabled:
        return None
    provider = settings.agent_llm_provider
    if provider == "anthropic" and settings.agent_llm_api_key:
        return AnthropicAgentLlmClient(
            api_key=settings.agent_llm_api_key,
            base_url=settings.agent_llm_base_url,
        )
    return None
