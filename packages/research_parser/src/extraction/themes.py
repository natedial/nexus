"""Extract themes from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .models import Theme
from .prompts import get_themes_prompt

logger = structlog.get_logger()

_THEMES_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "themes_response",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "coverage": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "themes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "label": {"type": "string"},
                            "excerpts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            },
                            "relevance": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "classification": {"type": "string"},
                            "mention_count": {"type": "number"},
                            "evidence_count": {"type": "number"},
                            "strength": {"type": "string"},
                            "directionality": {
                                "type": ["object", "null"],
                                "additionalProperties": {"type": "integer"},
                            },
                            "confidence": {"type": "string"},
                            "context": {"type": ["string", "null"]},
                        },
                        "required": [
                            "label",
                            "excerpts",
                            "relevance",
                            "classification",
                            "strength",
                            "confidence",
                            "context",
                        ],
                    },
                },
                "excluded_topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["themes"],
        },
    },
}


def _clean_json_response(text: str) -> str:
    """Clean JSON response from LLM (remove code fences, explanatory text, etc.)."""
    text = text.strip()

    # Find JSON array or object start
    json_start = -1
    for i, char in enumerate(text):
        if char in '[{':
            json_start = i
            break

    if json_start > 0:
        text = text[json_start:]

    # Remove trailing code fences
    if "```" in text:
        text = text.split("```")[0]

    return text.strip()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
def extract_themes(
    client: LLMClient,
    text: str,
    config: ModelConfig,
    log=None,
) -> list[Theme]:
    """
    Extract key themes from a financial research document.

    Uses extended thinking (if configured) for deeper reasoning about theme relationships.
    """
    thinking_enabled = config.extended_thinking and config.extended_thinking.enabled
    log = log or logger
    log.info(
        "Extracting themes",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
        thinking_enabled=thinking_enabled,
        thinking_budget=config.extended_thinking.budget_tokens if thinking_enabled else None,
    )

    raw = client.generate(
        config=config,
        system=get_themes_prompt(),
        user=text,
        response_format=_THEMES_RESPONSE_SCHEMA,
    )

    cleaned = _clean_json_response(raw)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "themes" in data:
            data = data["themes"]
        if not isinstance(data, list):
            data = [data]
        for theme in data:
            if "mention_count" not in theme and "evidence_count" in theme:
                theme["mention_count"] = theme["evidence_count"]
            directionality = theme.get("directionality")
            if isinstance(directionality, dict):
                cleaned = {}
                for key, value in directionality.items():
                    try:
                        cleaned[key] = int(value)
                    except (TypeError, ValueError):
                        continue
                theme["directionality"] = cleaned or None
            elif directionality is not None:
                theme["directionality"] = None
        themes = [Theme(**t) for t in data]
        log.info("Themes extracted", count=len(themes))
        return themes
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to parse themes JSON", error=str(e), raw=raw[:500])
        raise
