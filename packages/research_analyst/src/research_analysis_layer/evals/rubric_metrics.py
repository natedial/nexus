"""Slice 3 rubric rates and the advisory promotion gate.

Rates are aggregated from linted argument maps (Slice 1) and consensus /
divergence points (Slice 2). Floors and gate mode are config; the gate
stays advisory until a baseline file exists, then may warn or block.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_analysis_layer.evals.comparison import lint_argument_map

_ANALYTICAL_LENSES = frozenset({"thesis", "contrarian", "positioning"})
RUBRIC_RATE_NAMES = (
    "claim_rationale_rate",
    "claim_evidenced_rate",
    "divergence_grounded_rate",
    "divergence_attributed_rate",
    "consensus_multi_source_rate",
)


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _rate(numer: int, denom: int) -> float:
    if denom <= 0:
        return 1.0
    return numer / denom


def _publisher_key(name: Any) -> str:
    return str(name or "").strip()


def _is_lens(name: str) -> bool:
    return name.casefold() in _ANALYTICAL_LENSES


def _is_grounded_reason(reason: Any) -> bool:
    if not isinstance(reason, dict) and not hasattr(reason, "ref_key"):
        return False
    ref_key = _field(reason, "ref_key")
    text = str(_field(reason, "text", "") or "")
    return bool(str(ref_key or "").strip()) and bool(text.strip())


def _has_grounded_reason(reasons: Any) -> bool:
    return any(_is_grounded_reason(reason) for reason in (reasons or []))


def _is_attributed_publisher(name: Any) -> bool:
    publisher = _publisher_key(name)
    return bool(publisher) and not _is_lens(publisher)


def iter_claims(argument_maps: Any) -> list[Any]:
    """Flatten claim lists out of raw maps or consensus-store rows."""
    claims: list[Any] = []
    for item in argument_maps or []:
        if isinstance(item, dict) and "payload_json" in item:
            payload = item.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = None
            if isinstance(payload, dict):
                raw = payload.get("argument_map") or []
                if isinstance(raw, list):
                    claims.extend(raw)
            continue
        if isinstance(item, dict) and "argument_map" in item:
            raw = item.get("argument_map") or []
            if isinstance(raw, list):
                claims.extend(raw)
            continue
        if isinstance(item, list):
            claims.extend(item)
    return claims


def _iter_agreements(points: Any) -> list[Any]:
    if points is None:
        return []
    if isinstance(points, dict) and "agreements" in points:
        return list(points.get("agreements") or [])
    if not isinstance(points, dict) and hasattr(points, "agreements"):
        return list(getattr(points, "agreements") or [])
    return []


def _iter_disagreements(points: Any) -> list[Any]:
    if points is None:
        return []
    if isinstance(points, dict) and "disagreements" in points:
        return list(points.get("disagreements") or [])
    if not isinstance(points, dict) and hasattr(points, "disagreements"):
        return list(getattr(points, "disagreements") or [])
    return []


@dataclass
class RubricRates:
    """Corpus-level argumentation rubric rates (0–1)."""

    claim_rationale_rate: float
    claim_evidenced_rate: float
    divergence_grounded_rate: float
    divergence_attributed_rate: float
    consensus_multi_source_rate: float
    claim_count: int = 0
    evidenced_claim_count: int = 0
    divergence_side_count: int = 0
    consensus_point_count: int = 0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "claim_rationale_rate": self.claim_rationale_rate,
            "claim_evidenced_rate": self.claim_evidenced_rate,
            "divergence_grounded_rate": self.divergence_grounded_rate,
            "divergence_attributed_rate": self.divergence_attributed_rate,
            "consensus_multi_source_rate": self.consensus_multi_source_rate,
            "claim_count": self.claim_count,
            "evidenced_claim_count": self.evidenced_claim_count,
            "divergence_side_count": self.divergence_side_count,
            "consensus_point_count": self.consensus_point_count,
        }

    def rate_values(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in RUBRIC_RATE_NAMES}


def aggregate_rubric_metrics(
    argument_maps: Any = None,
    points: Any = None,
) -> RubricRates:
    """Aggregate Slice 1/2 rubric rates from linted maps and clustered points."""
    claims = iter_claims(argument_maps)
    missing_rationale = 0
    evidenced_total = 0
    evidenced_grounded = 0
    for claim in claims:
        violations = lint_argument_map([claim])
        codes = {item.code for item in violations}
        if "MISSING_RATIONALE" in codes:
            missing_rationale += 1
        if _field(claim, "support_strength") == "evidenced":
            evidenced_total += 1
            if "UNGROUNDED_EVIDENCED" not in codes:
                evidenced_grounded += 1

    sides: list[Any] = []
    for split in _iter_disagreements(points):
        sides.extend(list(_field(split, "sides", []) or []))
    grounded_sides = sum(
        1 for side in sides if _has_grounded_reason(_field(side, "reasons", []))
    )
    attributed_sides = sum(
        1 for side in sides if _is_attributed_publisher(_field(side, "position"))
    )

    agreements = _iter_agreements(points)
    multi_source = 0
    for point in agreements:
        publishers = {
            _publisher_key(name).casefold()
            for name in (_field(point, "positions", []) or [])
            if _publisher_key(name)
        }
        if len(publishers) >= 2:
            multi_source += 1

    return RubricRates(
        claim_rationale_rate=_rate(len(claims) - missing_rationale, len(claims)),
        claim_evidenced_rate=_rate(evidenced_grounded, evidenced_total),
        divergence_grounded_rate=_rate(grounded_sides, len(sides)),
        divergence_attributed_rate=_rate(attributed_sides, len(sides)),
        consensus_multi_source_rate=_rate(multi_source, len(agreements)),
        claim_count=len(claims),
        evidenced_claim_count=evidenced_total,
        divergence_side_count=len(sides),
        consensus_point_count=len(agreements),
    )


@dataclass
class PromotionGateDecision:
    """Result of comparing current rubric rates to configured floors."""

    action: str
    mode: str
    baseline_present: bool
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "mode": self.mode,
            "baseline_present": self.baseline_present,
            "failures": list(self.failures),
        }


def evaluate_promotion_gate(
    current: RubricRates | dict[str, float],
    *,
    floors: dict[str, float] | None = None,
    baseline: dict[str, float] | None = None,
    mode: str = "advisory",
) -> PromotionGateDecision:
    """Allow / warn / block `shadow → on` from rubric rates.

    No baseline → always allow (the gate only becomes active once a baseline
    exists). Advisory mode warns when a rate is below its floor; blocking
    mode returns ``block``. Floors default to 0.0 (never fail until calibrated).
    """
    gate_mode = (mode or "advisory").strip().lower()
    if gate_mode not in {"advisory", "blocking"}:
        gate_mode = "advisory"
    rates = current.rate_values() if isinstance(current, RubricRates) else dict(current)
    resolved_floors = {name: 0.0 for name in RUBRIC_RATE_NAMES}
    if floors:
        for name, value in floors.items():
            if name in resolved_floors:
                resolved_floors[name] = float(value)
    failures: list[str] = []
    for name in RUBRIC_RATE_NAMES:
        rate = float(rates.get(name, 1.0))
        if rate < resolved_floors[name]:
            failures.append(name)
    baseline_present = baseline is not None
    if not failures:
        action = "allow"
    elif not baseline_present:
        action = "allow"
    elif gate_mode == "blocking":
        action = "block"
    else:
        action = "warn"
    return PromotionGateDecision(
        action=action,
        mode=gate_mode,
        baseline_present=baseline_present,
        failures=failures,
    )


def load_rubric_baseline(path: Path | None) -> dict[str, float] | None:
    """Load saved rubric rates. Missing / unreadable files mean no baseline."""
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists() or not resolved.is_file():
        return None
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    metrics = raw.get("metrics") if isinstance(raw, dict) else None
    if not isinstance(metrics, dict):
        metrics = raw if isinstance(raw, dict) else {}
    rates: dict[str, float] = {}
    for name in RUBRIC_RATE_NAMES:
        value = metrics.get(name)
        if isinstance(value, (int, float)):
            rates[name] = float(value)
    return rates
