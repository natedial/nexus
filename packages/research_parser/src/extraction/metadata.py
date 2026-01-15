"""Extract metadata from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .models import Metadata
from .prompts import get_metadata_prompt

logger = structlog.get_logger()


def _extract_json_block(text: str) -> str:
    """Extract the first complete JSON object/array from text."""
    json_start = -1
    for i, char in enumerate(text):
        if char in "[{":
            json_start = i
            break

    if json_start == -1:
        return text

    stack: list[str] = []
    in_string = False
    escape = False
    for i in range(json_start, len(text)):
        char = text[i]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == "\"":
                in_string = False
            continue

        if char == "\"":
            in_string = True
            continue

        if char in "[{":
            stack.append(char)
            continue

        if char in "]}":
            if not stack:
                continue
            opener = stack.pop()
            if (opener == "[" and char != "]") or (opener == "{" and char != "}"):
                continue
            if not stack:
                return text[json_start : i + 1]

    return text[json_start:]


def _clean_json_response(text: str) -> str:
    """Clean JSON response from LLM (remove code fences, explanatory text, etc.)."""
    text = text.strip()

    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]

    text = _extract_json_block(text)

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
    log=None,
) -> Metadata:
    """
    Extract metadata from a financial research document.

    Uses the configured model to identify source, date, region, etc.
    """
    log = log or logger
    log.info(
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
        log.info("Metadata extracted", source=metadata.source, area=metadata.area)
        return metadata
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Failed to parse metadata JSON", error=str(e), raw=raw[:500])
        raise
