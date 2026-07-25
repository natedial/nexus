"""Deterministic prefiltering of Drive candidates before handing off to Codex.

Duplicate detection (same file_id/content_hash, or content hash seen under a
different file_id) is handled upstream in `drive_pull`. This module only
applies cheap, deterministic exclusions: file size and disclosure-ish
filenames.
"""

from __future__ import annotations

import re

import structlog

from morning_research.models import CandidateDoc

logger = structlog.get_logger()

# Case-insensitive filename patterns that indicate disclosure/boilerplate
# documents rather than substantive research.
_DISCLOSURE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"disclosure",
        r"disclaimer",
        r"legal[_\-\s]?notice",
        r"important[_\-\s]?information",
        r"terms[_\-\s]?of[_\-\s]?use",
        r"copyright[_\-\s]?notice",
    )
]


def _matches_disclosure_pattern(name: str) -> str | None:
    for pattern in _DISCLOSURE_PATTERNS:
        if pattern.search(name):
            return pattern.pattern
    return None


def prefilter(
    candidates: list[CandidateDoc], *, min_pdf_bytes: int
) -> tuple[list[CandidateDoc], list[CandidateDoc]]:
    """Split `candidates` into (kept, excluded).

    Excluded candidates have `.excluded = True` and `.exclusion_reason` set,
    and are returned separately so the manifest / receipt can record why they
    were dropped.
    """
    kept: list[CandidateDoc] = []
    excluded: list[CandidateDoc] = []

    for candidate in candidates:
        if candidate.size_bytes < min_pdf_bytes:
            candidate.excluded = True
            candidate.exclusion_reason = (
                f"size_bytes={candidate.size_bytes} < min_pdf_bytes={min_pdf_bytes}"
            )
            excluded.append(candidate)
            continue

        disclosure_match = _matches_disclosure_pattern(candidate.name)
        if disclosure_match:
            candidate.excluded = True
            candidate.exclusion_reason = f"filename_matches_disclosure_pattern:{disclosure_match}"
            excluded.append(candidate)
            continue

        kept.append(candidate)

    if excluded:
        logger.info(
            "Prefilter excluded candidates",
            excluded_count=len(excluded),
            kept_count=len(kept),
        )

    return kept, excluded
