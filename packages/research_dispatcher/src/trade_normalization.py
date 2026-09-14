"""Helpers for keeping trade expressions concise and displayable."""

from __future__ import annotations

import re


_RATIONALE_SPLIT_PATTERNS = (
    r"\s+\bon the view that\b",
    r"\s+\bbecause\b",
    r"\s+\bdue to\b",
    r"\s+\bgiven\b",
    r"\s+\bdriven by\b",
    r"\s+\breflecting\b",
    r"\s+\bas\b(?=\s+(?:inflation|growth|policy|supply|vol|volatility|macro|liquidity|carry|valuations?|positioning)\b)",
)


def normalize_trade_expression(
    text: str | None,
    *,
    max_words: int = 18,
    max_chars: int = 140,
) -> str:
    """Reduce a parsed trade blob to a short executable trade expression."""
    if not text:
        return ""

    cleaned = " ".join(str(text).split())
    if not cleaned:
        return ""

    for pattern in _RATIONALE_SPLIT_PATTERNS:
        cleaned = re.split(pattern, cleaned, maxsplit=1, flags=re.IGNORECASE)[0].strip()

    cleaned = re.split(r"(?<=[.!?;])\s+", cleaned, maxsplit=1)[0].strip()
    cleaned = cleaned.strip(" ,;:-")

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(",;:-")

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(",;:-")

    return cleaned


def dedupe_text_items(items: object, *, limit: int | None = None) -> list[str]:
    """Dedupe while preserving order and dropping empty items."""
    if not items:
        return []

    if isinstance(items, str):
        items = [items]
    elif not isinstance(items, (list, tuple, set)):
        return []

    deduped: list[str] = []
    seen: set[str] = set()

    for item in items:
        normalized = " ".join(str(item).split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if limit is not None and len(deduped) >= limit:
            break

    return deduped
