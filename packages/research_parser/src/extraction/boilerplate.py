"""Strip boilerplate text from financial research documents."""

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.llm import LLMClient, ModelConfig

from .prompts import get_boilerplate_prompt

logger = structlog.get_logger()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
def strip_boilerplate(
    client: LLMClient,
    text: str,
    config: ModelConfig,
) -> str:
    """
    Strip boilerplate sections from a financial research document.

    Uses the configured model to remove legal disclaimers, disclosures,
    and other non-research content.
    """
    logger.info(
        "Stripping boilerplate",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )

    result = client.generate(
        config=config,
        system=get_boilerplate_prompt(),
        user=text,
    )

    # Safeguard: if result is suspiciously short, fall back to original
    # This prevents downstream extraction from failing on empty/minimal content
    min_reasonable_length = min(2000, len(text) * 0.05)  # At least 5% or 2000 chars
    if len(result) < min_reasonable_length:
        logger.warning(
            "Boilerplate result suspiciously short, using original",
            original_length=len(text),
            result_length=len(result),
            min_threshold=min_reasonable_length,
        )
        return text

    logger.info(
        "Boilerplate stripped",
        original_length=len(text),
        result_length=len(result),
        reduction=f"{(1 - len(result) / len(text)) * 100:.1f}%",
    )

    return result
