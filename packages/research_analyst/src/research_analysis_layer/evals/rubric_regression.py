"""Rubric regression report over golden argument maps and consensus points.

Read-only over Slice 1/2 labels. Does not replace the final-output eval runner.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_analysis_layer.evals.comparison import lint_argument_map
from research_analysis_layer.evals.runner import load_golden_annotations

CONSENSUS_FILENAME = "consensus.jsonl"
_JUDGE_SCORE_KEYS = (
    "rationale_fidelity",
    "substantive_vs_framing",
    "groundedness",
    "phantom_counterparty",
)


def _rate(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return numer / denom


def _lint_points(points: list[Any]) -> list[Any] | None:
    """Use Slice 3 Task 2 linter when present; otherwise skip point rates."""
    from research_analysis_layer.evals import comparison as comparison_module

    lint_fn = getattr(comparison_module, "lint_consensus_divergence", None)
    if lint_fn is None:
        return None
    return list(lint_fn(points))


def _score_bundle(result: Any) -> dict[str, float] | None:
    scores = getattr(result, "scores_dict", None)
    if isinstance(scores, dict):
        return {str(k): float(v) for k, v in scores.items()}
    if isinstance(result, dict) and "scores" in result:
        raw = result.get("scores") or {}
        return {str(k): float(v) for k, v in raw.items()}
    return None


def load_golden_argument_maps(golden_path: Path) -> list[dict[str, Any]]:
    """Load hand-labeled `expected.argument_map` entries plus source text."""
    annotations = load_golden_annotations(golden_path)
    records: list[dict[str, Any]] = []
    for doc_id, ann in annotations.items():
        expected = ann.get("expected") or {}
        argument_map = expected.get("argument_map")
        if not isinstance(argument_map, list) or not argument_map:
            continue
        source = ""
        rel = ann.get("document_path")
        if rel:
            doc_path = golden_path / rel
            if doc_path.exists():
                source = doc_path.read_text(encoding="utf-8")
        records.append(
            {
                "document_id": doc_id,
                "argument_map": argument_map,
                "source_document": source,
            }
        )
    return records


def load_golden_consensus_points(golden_path: Path) -> list[dict[str, Any]]:
    """Load labeled consensus/divergence points from `consensus.jsonl`."""
    path = golden_path / CONSENSUS_FILENAME
    if not path.exists():
        return []
    points: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            points.append(item)
    return points


@dataclass
class RubricRegressionReport:
    """Summary of linter rates and optional judge scores vs a previous run."""

    total_claims: int
    total_maps: int
    total_points: int
    map_violation_rate: float
    map_violation_counts: dict[str, int]
    point_violation_rate: float | None
    point_violation_counts: dict[str, int]
    point_linter: str
    judge_scores: dict[str, float] | None
    delta_vs_previous: dict[str, float] = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_claims": self.total_claims,
            "total_maps": self.total_maps,
            "total_points": self.total_points,
            "map_violation_rate": self.map_violation_rate,
            "map_violation_counts": dict(self.map_violation_counts),
            "point_violation_rate": self.point_violation_rate,
            "point_violation_counts": dict(self.point_violation_counts),
            "point_linter": self.point_linter,
            "judge_scores": (
                dict(self.judge_scores) if self.judge_scores is not None else None
            ),
            "delta_vs_previous": dict(self.delta_vs_previous),
            "regressions": list(self.regressions),
        }


def _average_judge_scores(
    judge: Any,
    maps: list[dict[str, Any]],
    points: list[dict[str, Any]],
) -> dict[str, float] | None:
    if judge is None:
        return None
    collected: list[dict[str, float]] = []
    evaluate_claim = getattr(judge, "evaluate_claim", None)
    evaluate_point = getattr(judge, "evaluate_point", None)
    if callable(evaluate_claim):
        for record in maps:
            source = str(record.get("source_document") or "")
            for claim in record.get("argument_map") or []:
                bundle = _score_bundle(evaluate_claim(claim, source_document=source))
                if bundle:
                    collected.append(bundle)
    if callable(evaluate_point):
        for point in points:
            source = str(point.get("source_excerpt") or "")
            bundle = _score_bundle(evaluate_point(point, source_document=source))
            if bundle:
                collected.append(bundle)
    if not collected:
        return None
    keys = [key for key in _JUDGE_SCORE_KEYS if any(key in row for row in collected)]
    if not keys:
        keys = sorted({key for row in collected for key in row})
    averages: dict[str, float] = {}
    for key in keys:
        values = [row[key] for row in collected if key in row]
        if values:
            averages[key] = sum(values) / len(values)
    return averages or None


def _compare_to_previous(
    current: dict[str, float],
    previous: dict[str, Any] | None,
    *,
    lower_is_better: set[str],
) -> tuple[dict[str, float], list[str]]:
    if not previous:
        return {}, []
    deltas: dict[str, float] = {}
    regressions: list[str] = []
    for name, value in current.items():
        prior = previous.get(name)
        if not isinstance(prior, (int, float)):
            continue
        delta = float(value) - float(prior)
        deltas[name] = delta
        if name in lower_is_better:
            if delta > 1e-9:
                regressions.append(f"{name} rose {delta:.3f}")
        elif delta < -1e-9:
            regressions.append(f"{name} fell {abs(delta):.3f}")
    return deltas, regressions


def build_rubric_regression_report(
    golden_path: Path,
    *,
    previous: dict[str, Any] | Path | None = None,
    judge: Any | None = None,
) -> RubricRegressionReport:
    """Lint + optionally judge golden maps/points; diff against a previous report."""
    maps = load_golden_argument_maps(golden_path)
    points = load_golden_consensus_points(golden_path)

    map_counts: Counter[str] = Counter()
    total_claims = 0
    for record in maps:
        claims = list(record.get("argument_map") or [])
        total_claims += len(claims)
        for violation in lint_argument_map(claims):
            map_counts[violation.code] += 1

    point_counts: Counter[str] = Counter()
    point_rate: float | None = 0.0
    point_linter = "none"
    if points:
        point_result = _lint_points(points)
        if point_result is None:
            point_rate = None
            point_linter = "unavailable"
        else:
            for violation in point_result:
                code = getattr(violation, "code", None)
                if code:
                    point_counts[str(code)] += 1
            point_rate = _rate(sum(point_counts.values()), len(points))
            point_linter = "lint_consensus_divergence"

    judge_scores = _average_judge_scores(judge, maps, points)

    previous_data: dict[str, Any] | None
    if isinstance(previous, Path):
        previous_data = json.loads(previous.read_text(encoding="utf-8"))
    else:
        previous_data = previous
    if previous_data:
        flattened = dict(previous_data)
        nested = previous_data.get("judge_scores")
        if isinstance(nested, dict):
            for key, value in nested.items():
                flattened.setdefault(key, value)
        previous_data = flattened

    comparable: dict[str, float] = {
        "map_violation_rate": _rate(sum(map_counts.values()), total_claims),
    }
    if point_rate is not None:
        comparable["point_violation_rate"] = point_rate
    if judge_scores:
        comparable.update(judge_scores)

    lower_is_better = {"map_violation_rate", "point_violation_rate"}
    deltas, regressions = _compare_to_previous(
        comparable,
        previous_data,
        lower_is_better=lower_is_better,
    )

    return RubricRegressionReport(
        total_claims=total_claims,
        total_maps=len(maps),
        total_points=len(points),
        map_violation_rate=comparable["map_violation_rate"],
        map_violation_counts=dict(map_counts),
        point_violation_rate=point_rate,
        point_violation_counts=dict(point_counts),
        point_linter=point_linter,
        judge_scores=judge_scores,
        delta_vs_previous=deltas,
        regressions=regressions,
    )
