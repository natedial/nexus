"""Field-level comparison utilities for eval runner."""

from __future__ import annotations

import difflib
import re
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


@dataclass
class Violation:
    """A structured linter finding on an argument map or consensus payload."""

    code: str
    claim_index: int
    detail: str


_CLAIM_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)


def _item_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _normalize_claim_key(claim: str, stance: str | None) -> str:
    text = re.sub(r"[^\w\s]", " ", (claim or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    stance_n = (stance or "").strip().lower()
    return f"{text}|{stance_n}"


def _is_stopword_only(claim: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", (claim or "").lower())
    return not any(token not in _CLAIM_STOPWORDS for token in tokens)


def _has_grounded_evidence(item: Any) -> bool:
    evidence = _item_field(item, "evidence", []) or []
    for ref in evidence:
        ref_key = _item_field(ref, "ref_key") if not isinstance(ref, str) else None
        if ref_key:
            return True
    return False


def lint_argument_map(argument_map: Any) -> list[Violation]:
    """Deterministic quality checks over a per-document argument map.

    Accepts a list of ClaimNode instances or claim dicts. One malformed item
    never raises — it is reported as a violation when possible.
    """
    if not isinstance(argument_map, list):
        return []

    violations: list[Violation] = []
    seen_keys: dict[str, int] = {}

    for index, item in enumerate(argument_map):
        if not isinstance(item, dict) and not hasattr(item, "claim"):
            violations.append(
                Violation(
                    code="INVALID_CLAIM",
                    claim_index=index,
                    detail="claim item is not an object",
                )
            )
            continue

        claim = str(_item_field(item, "claim", "") or "")
        rationale = str(_item_field(item, "rationale", "") or "")
        stance = _item_field(item, "stance")
        support_strength = _item_field(item, "support_strength")

        if not rationale.strip():
            violations.append(
                Violation(
                    code="MISSING_RATIONALE",
                    claim_index=index,
                    detail="rationale is empty",
                )
            )

        if support_strength == "evidenced" and not _has_grounded_evidence(item):
            violations.append(
                Violation(
                    code="UNGROUNDED_EVIDENCED",
                    claim_index=index,
                    detail="evidenced claim has no grounded ref_key",
                )
            )

        if _is_stopword_only(claim):
            violations.append(
                Violation(
                    code="NONSUBSTANTIVE_CLAIM",
                    claim_index=index,
                    detail="claim is stopword-only or empty",
                )
            )

        key = _normalize_claim_key(claim, stance if isinstance(stance, str) else None)
        if key in seen_keys:
            violations.append(
                Violation(
                    code="DUPLICATE_CLAIM",
                    claim_index=index,
                    detail=f"duplicates claim at index {seen_keys[key]}",
                )
            )
        elif key.strip("|"):
            seen_keys[key] = index

    return violations


_ANALYTICAL_LENSES = frozenset({"thesis", "contrarian", "positioning"})


def _is_grounded_reason(reason: Any) -> bool:
    if not isinstance(reason, dict) and not hasattr(reason, "ref_key"):
        return False
    ref_key = _item_field(reason, "ref_key")
    text = str(_item_field(reason, "text", "") or "")
    return bool(str(ref_key or "").strip()) and bool(text.strip())


def _has_grounded_reason(reasons: Any) -> bool:
    return any(_is_grounded_reason(reason) for reason in (reasons or []))


def _normalize_publisher(name: Any) -> str:
    return str(name or "").strip()


def _publisher_key(name: str) -> str:
    return name.casefold()


def _is_lens_name(name: str) -> bool:
    return _publisher_key(name) in _ANALYTICAL_LENSES


def _flatten_points(points: Any) -> list[Any]:
    if points is None:
        return []
    if isinstance(points, dict) and (
        "agreements" in points or "disagreements" in points
    ):
        return list(points.get("agreements") or []) + list(
            points.get("disagreements") or []
        )
    if not isinstance(points, dict) and (
        hasattr(points, "agreements") or hasattr(points, "disagreements")
    ):
        return list(_item_field(points, "agreements", []) or []) + list(
            _item_field(points, "disagreements", []) or []
        )
    if isinstance(points, list):
        return points
    return [points]


def _is_divergence_point(item: Any) -> bool:
    if isinstance(item, dict):
        return "sides" in item
    return hasattr(item, "sides")


def _is_consensus_point(item: Any) -> bool:
    if isinstance(item, dict):
        return "positions" in item
    return hasattr(item, "positions")


def _read_verdict(item: Any) -> tuple[str | None, bool]:
    """Return (verdict, present). Empty/missing verdicts are not present."""
    if isinstance(item, dict):
        if "verdict" not in item:
            return None, False
        verdict = item.get("verdict")
    else:
        if not hasattr(item, "verdict"):
            return None, False
        verdict = getattr(item, "verdict")
    text = str(verdict or "").strip()
    if not text:
        return None, False
    return text, True


def lint_consensus_divergence(points: Any) -> list[Violation]:
    """Deterministic quality checks over Slice 2 consensus/divergence points.

    Accepts a list of ConsensusPoint / DivergencePoint instances or dicts, or
    a ConsensusSnapshot (agreements + disagreements). One malformed item never
    raises — it is reported as a violation when possible.
    """
    items = _flatten_points(points)
    violations: list[Violation] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict) and not (
            hasattr(item, "sides") or hasattr(item, "positions")
        ):
            violations.append(
                Violation(
                    code="INVALID_POINT",
                    claim_index=index,
                    detail="point is not an object",
                )
            )
            continue

        if _is_divergence_point(item):
            violations.extend(_lint_divergence_point(item, index))
        elif _is_consensus_point(item):
            violations.extend(_lint_consensus_point(item, index))
        else:
            violations.append(
                Violation(
                    code="INVALID_POINT",
                    claim_index=index,
                    detail="point is neither consensus nor divergence",
                )
            )

    return violations


def _lint_divergence_point(item: Any, index: int) -> list[Violation]:
    violations: list[Violation] = []
    sides = list(_item_field(item, "sides", []) or [])
    publishers = [_normalize_publisher(_item_field(side, "position")) for side in sides]
    distinct = {_publisher_key(name) for name in publishers if name}

    if len(sides) < 2:
        violations.append(
            Violation(
                code="TOO_FEW_SIDES",
                claim_index=index,
                detail=f"divergence has {len(sides)} side(s); need at least 2",
            )
        )
    elif len(distinct) < 2:
        violations.append(
            Violation(
                code="NON_DISTINCT_SIDES",
                claim_index=index,
                detail="divergence sides are not from distinct publishers",
            )
        )

    for side, publisher in zip(sides, publishers):
        if _is_lens_name(publisher):
            violations.append(
                Violation(
                    code="LENS_AS_POSITION",
                    claim_index=index,
                    detail=f"side {publisher!r} is an analytical lens, not a publisher",
                )
            )
        if not _has_grounded_reason(_item_field(side, "reasons", [])):
            label = publisher or "unknown"
            violations.append(
                Violation(
                    code="UNGROUNDED_SIDE",
                    claim_index=index,
                    detail=f"side {label} has no grounded reason",
                )
            )

    verdict, verdict_present = _read_verdict(item)
    if not verdict_present:
        violations.append(
            Violation(
                code="MISSING_VERDICT",
                claim_index=index,
                detail="divergence is missing a verdict",
            )
        )
    else:
        favored = _normalize_publisher(_item_field(item, "favored_position"))
        favored_verdict = verdict == "position_favored"
        if favored_verdict != bool(favored):
            if favored_verdict:
                detail = "favored_position must be set when verdict is position_favored"
            else:
                detail = (
                    "favored_position must be unset unless verdict is position_favored"
                )
            violations.append(
                Violation(
                    code="BAD_FAVORED_POSITION",
                    claim_index=index,
                    detail=detail,
                )
            )

    return violations


def _lint_consensus_point(item: Any, index: int) -> list[Violation]:
    violations: list[Violation] = []
    positions = [
        _normalize_publisher(name)
        for name in (_item_field(item, "positions", []) or [])
    ]
    distinct = {_publisher_key(name) for name in positions if name}

    if len(distinct) < 2:
        violations.append(
            Violation(
                code="TOO_FEW_PUBLISHERS",
                claim_index=index,
                detail=(
                    f"consensus has {len(distinct)} distinct publisher(s); "
                    "need at least 2"
                ),
            )
        )

    for publisher in positions:
        if _is_lens_name(publisher):
            violations.append(
                Violation(
                    code="LENS_AS_POSITION",
                    claim_index=index,
                    detail=(
                        f"position {publisher!r} is an analytical lens, "
                        "not a publisher"
                    ),
                )
            )

    if not _has_grounded_reason(_item_field(item, "reasons", [])):
        violations.append(
            Violation(
                code="MISSING_SHARED_REASON",
                claim_index=index,
                detail="consensus has no shared grounded reason",
            )
        )

    return violations
