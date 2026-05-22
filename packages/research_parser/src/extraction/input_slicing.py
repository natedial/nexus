"""Helpers for keeping structured extraction prompts within provider limits."""

import re

_MAX_STRUCTURED_TRIM_CHARS = 90_000
_MAX_STRUCTURED_CHUNK_CHARS = 24_000
_TARGET_STRUCTURED_CHUNK_CHARS = 16_000
_MIN_STRUCTURED_CHUNK_PROGRESS_CHARS = 8_000
_STRUCTURED_CHUNK_OVERLAP_CHARS = 2_000
_BOUNDARY_SNAP_WINDOW_CHARS = 1_000
_HEAD_CHARS = 18_000
_TAIL_CHARS = 12_000
_MIDDLE_WINDOWS = 4
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n")


def _middle_window_ranges(
    middle_length: int,
    window_count: int,
    total_budget: int,
) -> list[tuple[int, int]]:
    """Return evenly spaced windows across the middle of a document."""
    if middle_length <= 0 or window_count <= 0 or total_budget <= 0:
        return []

    window_size = max(total_budget // window_count, 1)
    if middle_length <= window_size * window_count:
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < middle_length and len(ranges) < window_count:
            end = min(start + window_size, middle_length)
            ranges.append((start, end))
            start = end
        return ranges

    ranges = []
    for idx in range(window_count):
        center = int((idx + 1) * middle_length / (window_count + 1))
        start = max(0, center - (window_size // 2))
        end = min(middle_length, start + window_size)
        start = max(0, end - window_size)
        ranges.append((start, end))
    return ranges


def trim_for_structured_extraction(text: str) -> str:
    """Keep head, tail, and evenly sampled middle windows from large documents."""
    if len(text) <= _MAX_STRUCTURED_TRIM_CHARS:
        return text

    head = text[:_HEAD_CHARS]
    tail = text[-_TAIL_CHARS:]
    middle = text[_HEAD_CHARS:-_TAIL_CHARS]

    separator = "\n\n[...]\n\n"
    middle_budget = _MAX_STRUCTURED_TRIM_CHARS - len(head) - len(tail)
    middle_budget -= len(separator) * (_MIDDLE_WINDOWS + 1)
    if middle_budget <= 0:
        return head + separator + tail

    sampled_middle = [
        middle[start:end]
        for start, end in _middle_window_ranges(
            middle_length=len(middle),
            window_count=_MIDDLE_WINDOWS,
            total_budget=middle_budget,
        )
        if start < end
    ]
    if not sampled_middle:
        return head + separator + tail

    return head + separator + separator.join(sampled_middle) + separator + tail


def _last_paragraph_boundary(text: str, start: int, end: int) -> int | None:
    boundary = None
    for match in _PARAGRAPH_BREAK_RE.finditer(text, start, end):
        boundary = match.start()
    return boundary


def _first_paragraph_boundary(text: str, start: int, end: int) -> int | None:
    match = _PARAGRAPH_BREAK_RE.search(text, start, end)
    if match is None:
        return None
    return match.end()


def chunk_for_structured_extraction(
    text: str,
    *,
    max_chunk_chars: int = _MAX_STRUCTURED_CHUNK_CHARS,
    target_chunk_chars: int = _TARGET_STRUCTURED_CHUNK_CHARS,
    min_progress_chars: int = _MIN_STRUCTURED_CHUNK_PROGRESS_CHARS,
    overlap_chars: int = _STRUCTURED_CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Split long documents into overlapping prompt-safe chunks.

    Chunks prefer paragraph boundaries when the document has them. This preserves
    coverage across the full note instead of sampling windows from the middle.
    """
    max_chunk_chars = max(int(max_chunk_chars), 1)
    target_chunk_chars = max(1, min(int(target_chunk_chars), max_chunk_chars))
    min_progress_chars = max(1, min(int(min_progress_chars), target_chunk_chars))
    overlap_chars = max(0, min(int(overlap_chars), max_chunk_chars - 1))

    if len(text) <= max_chunk_chars:
        return [text]

    text_length = len(text)
    chunks: list[str] = []
    start = 0

    while start < text_length:
        max_end = min(start + max_chunk_chars, text_length)
        target_end = min(start + target_chunk_chars, text_length)
        min_end = min(start + min_progress_chars, text_length)

        end = max_end
        snapped_end = _last_paragraph_boundary(text, min_end, max_end)
        if snapped_end is not None and snapped_end >= target_end:
            end = snapped_end
        elif snapped_end is not None and snapped_end > start:
            end = snapped_end

        chunk = text[start:end].strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)

        if end >= text_length:
            break

        next_start = max(end - overlap_chars, start + 1)
        snapped_start = _first_paragraph_boundary(
            text,
            next_start,
            min(end, next_start + _BOUNDARY_SNAP_WINDOW_CHARS),
        )
        if snapped_start is not None and snapped_start < end:
            next_start = snapped_start

        if next_start <= start:
            next_start = min(end, start + min_progress_chars)
        start = next_start

    return chunks
