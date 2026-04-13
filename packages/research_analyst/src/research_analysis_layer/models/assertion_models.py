"""Assertion draft models."""

from __future__ import annotations

from dataclasses import dataclass
import re


def normalize_text(value: str) -> str:
    """Normalize free text for matching and keys."""
    lowered = value.lower().strip()
    lowered = re.sub(r"[^a-z0-9\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


@dataclass(slots=True)
class AssertionDraft:
    """Bootstrap assertion representation."""

    chunk_order: int
    assertion_order: int
    assertion_type: str
    text: str
    normalized_text: str
    summary_text: str
    polarity: str = "not_applicable"
    confidence_label: str = "medium"
    extraction_confidence: str = "medium"
    time_horizon: str = "unknown"
    time_anchor: str | None = None
    condition_text: str | None = None
    qualifier_text: str | None = None
    status: str = "proposed"
    authority_band: str = "seed"
    subject_text: str | None = None
    object_text: str | None = None
