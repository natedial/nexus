"""Extract themes from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .models import Theme
from .prompts import get_themes_prompt

logger = structlog.get_logger()


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
) -> list[Theme]:
    """
    Extract key themes from a financial research document.

    Uses extended thinking (if configured) for deeper reasoning about theme relationships.
    """
    thinking_enabled = config.extended_thinking and config.extended_thinking.enabled
    logger.info(
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
    )

    cleaned = _clean_json_response(raw)

    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            data = [data]
        themes = [Theme(**t) for t in data]
        logger.info("Themes extracted", count=len(themes))
        return themes
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse themes JSON", error=str(e), raw=raw[:500])
        return []
