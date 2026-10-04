"""Deterministic shape/field eligibility for Nouls and fail-closed Fake mapping.

Shape-only: never consults significance, speaker weight, or "deserves a chart."
"""

from __future__ import annotations

from typing import Iterable

from src.graphic_selection.kit import kit_required_fields
from src.graphic_selection.question_set import shape_preference

# data_shape token → primary eligibility Noul id
SHAPE_TO_NOUL: dict[str, str] = {
    "scalars": "has_scalar_levels",
    "signed_changes": "has_signed_changes",
    "shares": "has_share_composition",
    "time_series": "has_aligned_time_series",
    "matrix": "has_matrix_cells",
    "range": "has_range_bounds",
    "ranked_list": "has_ranked_observations",
    "table": "has_tabular_cells",
    "caveat": "has_caveat_shape",
    "targets": "has_target_levels",
    "distribution": "has_distribution_bins",
    "events": "has_dated_events",
    "phases": "has_named_phases",
}

# Key fields that must be present for a pattern (subset of kit required_fields).
# Fail closed when these are absent even if Choice picks the pattern.
PATTERN_KEY_FIELDS: dict[str, list[str]] = {
    "metric_strip": ["label", "value"],
    "diverging_bars": ["category", "signed_change"],
    "small_multiples": ["series_label", "date", "value"],
    "composition_bars": ["component", "share", "denominator"],
    "heatmap": ["row", "column", "value"],
    "range_markers": ["category", "current", "low", "high"],
    "phase_cards": ["phase_name", "start", "end"],
    "ranked_rows": ["category", "signed_value", "date"],
    "context_table": ["row_label", "column_labels", "cell_values"],
    "annotation": ["statement", "evidence_reference"],
    "threshold_tracker": ["item", "current", "target"],
    "distribution": ["bin_edges", "bin_counts", "sample_size"],
    "event_timeline": ["date", "event_title"],
    "prose": [],
}


def normalize_fields(fields: Iterable[str] | None) -> set[str]:
    return {str(item).strip() for item in (fields or []) if str(item).strip()}


def pattern_fields_satisfied(pattern_id: str, available_fields: Iterable[str]) -> bool:
    """True when key fields for ``pattern_id`` are present (prose always ok)."""
    if pattern_id == "prose":
        return True
    present = normalize_fields(available_fields)
    keys = PATTERN_KEY_FIELDS.get(pattern_id)
    if keys is None:
        # Unknown pattern → consult full kit required_fields, fail closed if missing.
        keys = kit_required_fields(pattern_id)
        if not keys:
            return False
    return all(field in present for field in keys)


def preferred_pattern_for_shape(data_shape: str) -> str:
    pref = shape_preference()
    return pref.get(data_shape, pref.get("none", "prose"))


def map_shape_to_pattern(
    data_shape: str,
    available_fields: Iterable[str] | None = None,
) -> str:
    """Fail-closed shape→pattern map used by FakeDecisionModel default Choice."""
    pattern = preferred_pattern_for_shape(data_shape or "none")
    if not pattern_fields_satisfied(pattern, available_fields or []):
        return "prose"
    return pattern


def eligibility_flags(
    data_shape: str,
    available_fields: Iterable[str] | None = None,
) -> dict[str, bool]:
    """Deterministic Noul answers from shape + field presence."""
    fields = normalize_fields(available_fields)
    shape = (data_shape or "none").strip() or "none"
    preferred = preferred_pattern_for_shape(shape)
    shape_ok = shape != "none" and pattern_fields_satisfied(preferred, fields)

    flags: dict[str, bool] = {noul_id: False for noul_id in SHAPE_TO_NOUL.values()}
    noul_id = SHAPE_TO_NOUL.get(shape)
    if noul_id is not None:
        flags[noul_id] = shape_ok
    return flags


__all__ = [
    "PATTERN_KEY_FIELDS",
    "SHAPE_TO_NOUL",
    "eligibility_flags",
    "map_shape_to_pattern",
    "normalize_fields",
    "pattern_fields_satisfied",
    "preferred_pattern_for_shape",
]
