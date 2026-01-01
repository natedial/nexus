"""Extract trade ideas from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .models import Trade
from .prompts import get_trades_prompt

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
def extract_trades(
    client: LLMClient,
    text: str,
    config: ModelConfig,
) -> list[Trade]:
    """
    Extract explicit trade ideas from a financial research document.

    Identifies positioning recommendations with conviction and timeframe.
    """
    logger.info(
        "Extracting trades",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )

    raw = client.generate(
        config=config,
        system=get_trades_prompt(),
        user=text,
    )

    cleaned = _clean_json_response(raw)

    try:
        data = json.loads(cleaned)
        if not isinstance(data, list):
            data = [data] if data else []
        trades = [Trade(**t) for t in data]
        logger.info("Trades extracted", count=len(trades))
        return trades
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse trades JSON", error=str(e), raw=raw[:500])
        return []
