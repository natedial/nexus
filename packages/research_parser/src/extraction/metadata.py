"""Extract metadata from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .models import Metadata
from .prompts import get_metadata_prompt

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
def extract_metadata(
    client: LLMClient,
    text: str,
    config: ModelConfig,
) -> Metadata:
    """
    Extract metadata from a financial research document.

    Uses the configured model to identify source, date, region, etc.
    """
    logger.info(
        "Extracting metadata",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )

    raw = client.generate(
        config=config,
        system=get_metadata_prompt(),
        user=text[:15000],  # Truncate for metadata extraction
    )

    cleaned = _clean_json_response(raw)

    try:
        data = json.loads(cleaned)
        metadata = Metadata(**data)
        logger.info("Metadata extracted", source=metadata.source, area=metadata.area)
        return metadata
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse metadata JSON", error=str(e), raw=raw[:500])
        # Return defaults
        return Metadata()
