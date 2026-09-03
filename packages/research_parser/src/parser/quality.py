"""Decide when a digital parse should be retried with OCR."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .backend import BlockType

if TYPE_CHECKING:
    from .routing import ParsedDocument

_LOW_TEXT_PER_PAGE = 300
_FIGURE_RATIO = 0.3
_STUB_FIGURE_RATIO = 0.25
_OCR_TEXT_GAIN = 1.15
_STUB_CAPTION_RE = re.compile(r"^(figure|image|chart|table)(\s+\d+)?$", re.I)
_PASS_OCR_REASONS = frozenset({"missing_pages", "low_text_per_page"})


def _block_chars(parsed: ParsedDocument) -> int:
    return sum(len((block.text or "").strip()) for block in parsed.text_result.blocks)


def _is_stub_caption(text: str) -> bool:
    """True for generic placeholders, not real exhibit titles."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    return bool(_STUB_CAPTION_RE.fullmatch(stripped))


def _expected_pages(parsed: ParsedDocument) -> tuple[set[int], set[int]]:
    """Return (pages_with_blocks, expected_page_set)."""
    pages = {block.page for block in parsed.text_result.blocks if block.page and block.page > 0}
    source_page_count = parsed.text_result.source_page_count
    if isinstance(source_page_count, int) and source_page_count > 0:
        return pages, set(range(1, source_page_count + 1))
    if len(pages) >= 2:
        return pages, set(range(min(pages), max(pages) + 1))
    return pages, set()


def ocr_retry_reasons(parsed: ParsedDocument) -> list[str]:
    """Return why a digital parse should get an OCR retry.

    Digital text stays the default. Chart-heavy notes that already extracted
    well (PASS, all pages present, enough text) skip OCR even when they contain
    figures. We only spend OCR on gappy or image-stub parses:
    missing pages, thin text-per-page, stub figure captions, or FALLBACK.
    PASS still retries when pages are missing or text-per-page is thin, because
    those are the unpredictable scanned/exhibit tails.
    """
    blocks = parsed.text_result.blocks
    reasons: list[str] = []
    pages, expected = _expected_pages(parsed)
    if expected:
        if expected - pages:
            reasons.append("missing_pages")
        chars = _block_chars(parsed)
        if chars / max(len(expected), 1) < _LOW_TEXT_PER_PAGE:
            reasons.append("low_text_per_page")

    figure_blocks = [block for block in blocks if block.block_type == BlockType.FIGURE_REF]
    if blocks and len(figure_blocks) / len(blocks) >= _FIGURE_RATIO:
        stubs = [block for block in figure_blocks if _is_stub_caption(block.text)]
        if figure_blocks and len(stubs) / len(figure_blocks) >= _STUB_FIGURE_RATIO:
            reasons.append("stub_figures")

    if parsed.confidence.status == "FALLBACK":
        reasons.append("confidence_fallback")

    if parsed.confidence.status == "PASS":
        return [reason for reason in reasons if reason in _PASS_OCR_REASONS]
    return reasons


def prefer_parse(first: ParsedDocument, second: ParsedDocument) -> ParsedDocument:
    """Keep the OCR pass only when it adds text or clearly improves confidence."""
    first_chars = _block_chars(first)
    second_chars = _block_chars(second)
    if second_chars >= max(int(first_chars * _OCR_TEXT_GAIN), first_chars + 1):
        return second
    if second.confidence.score > first.confidence.score + 0.05:
        return second
    return first
