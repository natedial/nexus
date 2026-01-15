"""Strip boilerplate text from financial research documents."""

import structlog
import re
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
    log=None,
    deterministic_only: bool = False,
) -> str:
    """
    Strip boilerplate sections from a financial research document.

    Uses the configured model to remove legal disclaimers, disclosures,
    and other non-research content.
    """
    log = log or logger
    log.info(
        "Stripping boilerplate",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )

    deterministic, match_info = _strip_boilerplate_deterministic(text)
    if deterministic is not None:
        log.info(
            "Boilerplate stripped (deterministic)",
            original_length=len(text),
            result_length=len(deterministic),
            reduction=f"{(1 - len(deterministic) / len(text)) * 100:.1f}%",
            match_info=match_info,
        )
        return deterministic
    if match_info is not None:
        log.info("Boilerplate header match ignored (too early)", match_info=match_info)
    if deterministic_only:
        log.info("Boilerplate header not found, deterministic-only enabled")
        return text
    log.info("Boilerplate header not found, falling back to LLM")

    result = client.generate(
        config=config,
        system=get_boilerplate_prompt(),
        user=text,
    )

    # Safeguard: if result is suspiciously short, fall back to original
    # This prevents downstream extraction from failing on empty/minimal content
    min_reasonable_length = min(2000, len(text) * 0.05)  # At least 5% or 2000 chars
    reduction = 1 - (len(result) / len(text)) if text else 0
    max_reasonable_reduction = 0.90
    placeholder_markers = (
        "[remaining content",
        "[content omitted",
        "[exhibits",
        "the rest of the document continues",
        "with boilerplate sections removed",
        "here is the filtered document",
        "i will filter the document",
        "document remains unchanged",
    )
    placeholder_detected = any(marker in result.lower() for marker in placeholder_markers)
    if len(result) < min_reasonable_length or reduction > max_reasonable_reduction or placeholder_detected:
        sample_len = 500
        log.warning(
            "Boilerplate result suspiciously short, using original",
            original_length=len(text),
            result_length=len(result),
            min_threshold=min_reasonable_length,
            reduction=f"{reduction * 100:.1f}%",
            max_reduction=f"{max_reasonable_reduction * 100:.0f}%",
            placeholder_detected=placeholder_detected,
            result_preview_start=result[:sample_len],
            result_preview_end=result[-sample_len:] if len(result) > sample_len else "",
        )
        return text

    log.info(
        "Boilerplate stripped",
        original_length=len(text),
        result_length=len(result),
        reduction=f"{(1 - len(result) / len(text)) * 100:.1f}%",
    )

    return result


_BOILERPLATE_HEADERS = [
    "appendix",
    "analyst certification",
    "important disclosure",
    "important disclosures",
    "additional information",
    "legal disclaimer",
    "regulatory disclosure",
    "regulatory disclosures",
    "conflict of interest",
    "distribution",
    "copyright",
]


def _strip_boilerplate_deterministic(text: str) -> tuple[str | None, dict | None]:
    """Strip boilerplate by truncating from the first boilerplate header."""
    lines = text.splitlines()
    total_lines = max(len(lines), 1)
    min_fraction = 0.7  # Boilerplate is expected near the end.
    first_early_match = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Skip very long lines to avoid matching within paragraphs.
        if len(stripped) > 120:
            continue
        normalized = re.sub(r"^[\W_]*(\d+(\.\d+)*)\s+|[\s:—-]+$", "", stripped).lower()
        for header in _BOILERPLATE_HEADERS:
            if normalized == header or header in normalized:
                match_info = {"line_index": idx + 1, "total_lines": total_lines, "line": stripped}
                if (idx / total_lines) >= min_fraction:
                    return "\n".join(lines[:idx]).rstrip(), match_info
                if first_early_match is None:
                    first_early_match = match_info
                break
    return None, first_early_match
