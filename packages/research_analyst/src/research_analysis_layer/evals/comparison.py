"""Field-level comparison utilities for eval runner."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any


DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
    "thesis": 0.25,
    "key_claims_claim": 0.15,
    "trading_opportunities_thesis": 0.20,
    "trading_opportunities_direction": 0.10,
    "talking_points_text": 0.15,
    "confidence": 0.15,
}


def rouge_l(actual: str, expected: str) -> float:
    """Compute ROUGE-L (longest common subsequence) F1 score.

    No new dependencies - uses difflib internally.
    ROUGE-L uses the full LCS (all matching blocks), not just longest contiguous.
    """
    if not actual and not expected:
        return 1.0
    if not actual or not expected:
        return 0.0

    actual_words = actual.split()
    expected_words = expected.split()

    matcher = difflib.SequenceMatcher(None, actual_words, expected_words)
    matching_blocks = matcher.get_matching_blocks()
    lcs_length = sum(block.size for block in matching_blocks)

    if lcs_length == 0:
        return 0.0

    precision = lcs_length / len(actual_words)
    recall = lcs_length / len(expected_words)

    if precision + recall == 0:
        return 0.0

    f1 = 2 * precision * recall / (precision + recall)
    return f1


def list_match_rate(
    actual: list[Any], expected: list[Any], threshold: float = 0.7
) -> float:
    """Compute match rate between two lists using fuzzy matching.

    Uses difflib.SequenceMatcher with threshold 0.7.
    Score = matched_items / max(len(actual), len(expected))
    """
    if not actual and not expected:
        return 1.0
    if not actual or not expected:
        return 0.0

    actual_strs = [str(x) for x in actual]
    expected_strs = [str(x) for x in expected]

    matched = 0
    for a in actual_strs:
        best_ratio = (
            max(difflib.SequenceMatcher(None, a, e).ratio() for e in expected_strs)
            if expected_strs
            else 0.0
        )
        if best_ratio >= threshold:
            matched += 1

    return matched / max(len(actual), len(expected))


def exact_match(actual: Any, expected: Any) -> float:
    """Exact match comparison - returns 1.0 if equal, 0.0 otherwise."""
    return 1.0 if actual == expected else 0.0


def confidence_delta(actual: float, expected: float, tolerance: float = 0.1) -> float:
    """Compare confidence values with tolerance threshold."""
    delta = abs(actual - expected)
    if delta <= tolerance:
        return 1.0
    return max(0.0, 1.0 - (delta - tolerance) / (1.0 - tolerance))


def structured_match_score(
    actual: dict[str, Any],
    expected: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> float:
    """Compare structured outputs (dicts) field by field.

    Each field is compared using the appropriate method based on its type.
    """
    if not actual and not expected:
        return 1.0
    if not actual or not expected:
        return 0.0

    weights = weights or {}
    all_keys = set(actual.keys()) | set(expected.keys())

    if not all_keys:
        return 1.0

    total_weight = 0.0
    weighted_score = 0.0

    for key in all_keys:
        weight = weights.get(key, 1.0 / len(all_keys))
        a_val = actual.get(key)
        e_val = expected.get(key)

        score = compute_field_similarity(a_val, e_val)

        weighted_score += score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return weighted_score / total_weight


def compute_field_similarity(
    actual: Any,
    expected: Any,
    field_type: str = "text",
) -> float:
    """Compute similarity between actual and expected values.

    Args:
        actual: The actual output value
        expected: The expected/golden value
        field_type: One of "text", "list", "structured", "exact", "confidence"

    Returns:
        Similarity score between 0.0 and 1.0
    """
    if field_type == "text":
        return rouge_l(str(actual), str(expected))
    elif field_type == "list":
        return list_match_rate(actual, expected)
    elif field_type == "structured":
        return structured_match_score(actual, expected)
    elif field_type == "exact":
        return exact_match(actual, expected)
    elif field_type == "confidence":
        try:
            return confidence_delta(float(actual), float(expected))
        except (TypeError, ValueError):
            return 0.0
    else:
        return rouge_l(str(actual), str(expected))


def compute_confidence(field_scores: dict[str, float]) -> float:
    """Compute weighted confidence score from field scores.

    Uses DEFAULT_FIELD_WEIGHTS to compute weighted average.
    """
    if not field_scores:
        return 0.0

    total_weight = 0.0
    weighted_score = 0.0

    for field, score in field_scores.items():
        weight = DEFAULT_FIELD_WEIGHTS.get(field, 0.0)
        if weight > 0:
            weighted_score += score * weight
            total_weight += weight

    if total_weight == 0:
        return sum(field_scores.values()) / len(field_scores) if field_scores else 0.0

    return weighted_score / total_weight


@dataclass
class FieldComparisonResult:
    """Result of comparing a single field."""

    field_name: str
    actual: Any
    expected: Any
    score: float
    method: str


def compare_outputs(
    actual: dict[str, Any],
    expected: dict[str, Any],
    field_schema: dict[str, str] | None = None,
) -> dict[str, float]:
    """Compare actual output to expected output across defined fields.

    Args:
        actual: The actual agent output
        expected: The golden/expected output
        field_schema: Mapping of field names to comparison methods.
                     If None, uses heuristic detection.

    Returns:
        Dict of field_name -> similarity score
    """
    default_schema = {
        "thesis": "text",
        "key_claims": "list",
        "trading_opportunities": "list",
        "talking_points": "list",
        "confidence": "confidence",
    }
    schema = field_schema or default_schema

    results = {}

    for field, method in schema.items():
        a_val = actual.get(field)
        e_val = expected.get(field)

        if a_val is None and e_val is None:
            results[field] = 1.0
            continue

        if method == "list" and isinstance(e_val, list):
            if field == "key_claims":
                actual_items = [x.get("claim", "") for x in (a_val or [])]
                expected_items = [x.get("claim", "") for x in e_val]
                results["key_claims_claim"] = list_match_rate(
                    actual_items, expected_items
                )
            elif field == "trading_opportunities":
                actual_items = [x.get("thesis", "") for x in (a_val or [])]
                expected_items = [x.get("thesis", "") for x in e_val]
                results["trading_opportunities_thesis"] = list_match_rate(
                    actual_items, expected_items
                )

                actual_dirs = [x.get("direction", "") for x in (a_val or [])]
                expected_dirs = [x.get("direction", "") for x in e_val]
                results["trading_opportunities_direction"] = list_match_rate(
                    actual_dirs, expected_dirs
                )
            elif field == "talking_points":
                actual_items = [x.get("text", "") for x in (a_val or [])]
                expected_items = [x.get("text", "") for x in e_val]
                results["talking_points_text"] = list_match_rate(
                    actual_items, expected_items
                )
            else:
                results[field] = list_match_rate(a_val, e_val)
        else:
            results[field] = compute_field_similarity(a_val, e_val, method)

    return results
