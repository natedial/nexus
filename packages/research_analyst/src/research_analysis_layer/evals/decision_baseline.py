"""Deterministic baseline mappings for shadow classification metrics."""

from __future__ import annotations

from research_analysis_layer.models.decision_models import SUBTYPE_NOUL_IDS

# Choice baseline: map deterministic assertion_type -> statement_type.
# evidence_report and background_methodology stay unmapped.
CHOICE_BASELINE_MAP: dict[str, str] = {
    "open_question": "question",
    "trade_claim": "recommendation",
    "forecast": "assertion",
    "causal_claim": "assertion",
    "market_impact": "assertion",
    "policy_claim": "assertion",
    "risk_condition": "assertion",
    "observation": "assertion",
}

UNMAPPED_CHOICE_LABELS: frozenset[str] = frozenset(
    {"evidence_report", "background_methodology"}
)

# Overlapping subtype Nouls where semantics align with deterministic types.
SUBTYPE_BASELINE_MAP: dict[str, str] = {
    "forecast": "is_forecast",
    "causal_claim": "is_causal",
    "market_impact": "is_market_impact",
    "policy_claim": "is_policy_claim",
    "risk_condition": "is_risk_or_scenario",
    "trade_claim": "is_trade_or_action",
    "observation": "is_observation",
}


def map_choice_baseline(assertion_type: str | None) -> str | None:
    """Return mapped Choice label, or None when unmapped / unknown."""
    if not assertion_type:
        return None
    return CHOICE_BASELINE_MAP.get(assertion_type)


def map_subtype_baseline(assertion_type: str | None) -> str | None:
    """Return the overlapping subtype Noul ID for a deterministic type."""
    if not assertion_type:
        return None
    noul_id = SUBTYPE_BASELINE_MAP.get(assertion_type)
    if noul_id is not None and noul_id not in SUBTYPE_NOUL_IDS:
        return None
    return noul_id


def baseline_limitations() -> dict[str, object]:
    """Document explicit mapping limits for reports."""
    return {
        "choice_unmapped_labels": sorted(UNMAPPED_CHOICE_LABELS),
        "choice_notes": (
            "evidence_report and background_methodology have no deterministic "
            "assertion_type counterpart and are excluded from Choice baseline "
            "comparisons rather than forced into incorrect buckets."
        ),
        "subtype_notes": (
            "Only overlapping subtype Nouls listed in SUBTYPE_BASELINE_MAP are "
            "compared; is_comparative and support/grounding Nouls have no "
            "deterministic baseline."
        ),
        "choice_map": dict(CHOICE_BASELINE_MAP),
        "subtype_map": dict(SUBTYPE_BASELINE_MAP),
    }
