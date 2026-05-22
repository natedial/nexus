"""Extract metadata from financial research documents."""

import json

import structlog
from tenacity import retry, stop_after_attempt, wait_random_exponential

from src.llm import LLMClient, ModelConfig

from .json_utils import clean_json_response
from .models import Metadata
from .prompts import get_metadata_prompt
from .structured import generate_with_validation_fallback

logger = structlog.get_logger()

# Truncation budget for metadata extraction
_HEAD_CHARS = 10_000
_TAIL_CHARS = 5_000


def _truncate_for_metadata(text: str) -> str:
    """Return head + tail of the document so metadata extraction sees both
    the front-matter (title, source, date) and back-matter (disclaimers
    that often contain publisher/date info)."""
    if len(text) <= _HEAD_CHARS + _TAIL_CHARS:
        return text
    return text[:_HEAD_CHARS] + "\n\n[...]\n\n" + text[-_TAIL_CHARS:]


def _parse_metadata_response(raw: str) -> Metadata:
    cleaned = clean_json_response(raw)
    data = json.loads(cleaned)
    return Metadata(**data)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_random_exponential(multiplier=1, min=2, max=45),
    reraise=True,
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

    metadata = generate_with_validation_fallback(
        client=client,
        config=config,
        system=get_metadata_prompt(),
        user=_truncate_for_metadata(text),
        parser=_parse_metadata_response,
        log=log,
        step="metadata",
    )
    log.info("Metadata extracted", source=metadata.source, area=metadata.area)
    return metadata
