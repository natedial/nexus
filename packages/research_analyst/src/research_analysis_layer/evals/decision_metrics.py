"""Metrics for shadow decision-classification evaluation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from research_analysis_layer.evals.decision_baseline import (
    baseline_limitations,
    map_choice_baseline,
    map_subtype_baseline,
)
from research_analysis_layer.evals.decision_question_set import STATEMENT_TYPE_QUESTION_ID
from research_analysis_layer.models.decision_models import (
    SUBTYPE_NOUL_IDS,
    SUPPORT_NOUL_IDS,
    ShadowClassificationArtifact,
    UnitClassificationRecord,
)

NOUL_QUESTION_IDS: tuple[str, ...] = (*SUBTYPE_NOUL_IDS, *SUPPORT_NOUL_IDS)


@dataclass(slots=True)
class GoldUnitLabel:
    """Hand-authored gold labels for one assertion unit."""

    unit_id: str
    statement_type: str
    noul_labels: dict[str, bool] = field(default_factory=dict)
    assertion_type: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class ClassificationMetricsReport:
    """Compact metrics payload for fixture / held-out evaluation."""

    unit_count: int
    choice_support: int
    choice_accuracy: float | None
    choice_macro_f1: float | None
    choice_confusion: dict[str, dict[str, int]]
    noul_precision: dict[str, float | None]
    noul_recall: dict[str, float | None]
    noul_support: dict[str, int]
    abstention_rate: float
    uncertain_rate: float
    coverage_full_rate: float
    coverage_partial_rate: float
    incomplete_batch_rate: float
    permanent_error_rate: float
    provenance_coverage_rate: float
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    provider_cost: dict[str, Any]
    baseline_choice_agreement: float | None
    baseline_choice_compared: int
    baseline_subtype_agreement: float | None
    baseline_subtype_compared: int
    baseline_limitations: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_shadow_artifact(
    artifact: ShadowClassificationArtifact,
    gold_labels: Sequence[GoldUnitLabel] | Mapping[str, GoldUnitLabel],
    *,
    noul_threshold: float = 0.5,
) -> ClassificationMetricsReport:
    """Score an artifact against gold labels and deterministic baselines."""
    gold_by_id = (
        dict(gold_labels)
        if isinstance(gold_labels, Mapping)
        else {label.unit_id: label for label in gold_labels}
    )
    records = [unit for unit in artifact.units if unit.unit_id in gold_by_id]

    choice_pairs: list[tuple[str, str]] = []
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    noul_tp: Counter[str] = Counter()
    noul_fp: Counter[str] = Counter()
    noul_fn: Counter[str] = Counter()
    noul_support: Counter[str] = Counter()

    abstentions = 0
    uncertains = 0
    result_count = 0
    latencies: list[float] = []
    provenance_hits = 0

    for record in records:
        gold = gold_by_id[record.unit_id]
        if record.provenance.get("assertion_key") or record.provenance.get("span_key"):
            provenance_hits += 1
        if record.latency_ms is not None:
            latencies.append(float(record.latency_ms))

        for result in record.results:
            result_count += 1
            if result.status in {"failed", "none"}:
                abstentions += 1
            if result.status == "uncertain":
                uncertains += 1

            if result.question_id == STATEMENT_TYPE_QUESTION_ID:
                predicted = _selected_label(result, noul_threshold=noul_threshold)
                if predicted is None:
                    continue
                choice_pairs.append((gold.statement_type, predicted))
                confusion[gold.statement_type][predicted] += 1
                continue

            if result.question_id not in NOUL_QUESTION_IDS:
                continue
            if result.question_id not in gold.noul_labels:
                continue
            gold_yes = bool(gold.noul_labels[result.question_id])
            noul_support[result.question_id] += 1
            pred_yes = _noul_positive(result, threshold=noul_threshold)
            if pred_yes is None:
                abstentions += 1
                continue
            if pred_yes and gold_yes:
                noul_tp[result.question_id] += 1
            elif pred_yes and not gold_yes:
                noul_fp[result.question_id] += 1
            elif (not pred_yes) and gold_yes:
                noul_fn[result.question_id] += 1

    choice_accuracy = None
    choice_macro_f1 = None
    if choice_pairs:
        correct = sum(1 for gold, pred in choice_pairs if gold == pred)
        choice_accuracy = correct / len(choice_pairs)
        choice_macro_f1 = _macro_f1(choice_pairs)

    noul_precision: dict[str, float | None] = {}
    noul_recall: dict[str, float | None] = {}
    for qid in NOUL_QUESTION_IDS:
        tp = noul_tp[qid]
        fp = noul_fp[qid]
        fn = noul_fn[qid]
        noul_precision[qid] = (tp / (tp + fp)) if (tp + fp) else None
        noul_recall[qid] = (tp / (tp + fn)) if (tp + fn) else None

    coverage_counts = Counter(record.coverage_status for record in artifact.units)
    unit_total = max(1, len(artifact.units))
    batch_total = max(1, len(artifact.batch_results))

    baseline_choice_agree, baseline_choice_n = _baseline_choice_agreement(records)
    baseline_subtype_agree, baseline_subtype_n = _baseline_subtype_agreement(
        records, noul_threshold=noul_threshold
    )

    notes = [
        "calibrated_probability is null in v1; raw_probability is scored as-is",
        "AUROC/AUPRC and Brier/ECE deferred until larger labeled splits exist",
    ]

    return ClassificationMetricsReport(
        unit_count=len(records),
        choice_support=len(choice_pairs),
        choice_accuracy=choice_accuracy,
        choice_macro_f1=choice_macro_f1,
        choice_confusion={
            label: dict(counter) for label, counter in sorted(confusion.items())
        },
        noul_precision=noul_precision,
        noul_recall=noul_recall,
        noul_support=dict(noul_support),
        abstention_rate=(abstentions / result_count) if result_count else 0.0,
        uncertain_rate=(uncertains / result_count) if result_count else 0.0,
        coverage_full_rate=coverage_counts.get("full", 0) / unit_total,
        coverage_partial_rate=coverage_counts.get("partial", 0) / unit_total,
        incomplete_batch_rate=artifact.incomplete_batch_count / batch_total,
        permanent_error_rate=artifact.permanent_error_count
        / max(1, sum(len(u.results) for u in artifact.units) + artifact.permanent_error_count),
        provenance_coverage_rate=(provenance_hits / len(records)) if records else 0.0,
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        provider_cost=estimate_usage_cost(
            artifact.usage, provider=artifact.provider
        ),
        baseline_choice_agreement=baseline_choice_agree,
        baseline_choice_compared=baseline_choice_n,
        baseline_subtype_agreement=baseline_subtype_agree,
        baseline_subtype_compared=baseline_subtype_n,
        baseline_limitations=baseline_limitations(),
        notes=notes,
    )


def choice_prediction(
    record: UnitClassificationRecord, *, noul_threshold: float = 0.5
) -> tuple[str | None, float | None]:
    """Return (selected statement type, raw probability) for a unit."""
    result = next(
        (item for item in record.results if item.question_id == STATEMENT_TYPE_QUESTION_ID),
        None,
    )
    if result is None:
        return None, None
    return _selected_label(result, noul_threshold=noul_threshold), _raw_probability(result)


def noul_prediction(
    record: UnitClassificationRecord,
    question_id: str,
    *,
    threshold: float = 0.5,
) -> tuple[bool | None, float | None]:
    """Return (yes/no/None, raw probability) for one binary question."""
    result = next(
        (item for item in record.results if item.question_id == question_id),
        None,
    )
    if result is None:
        return None, None
    return _noul_positive(result, threshold=threshold), _raw_probability(result)


def _raw_probability(result: Any) -> float | None:
    if result.distribution is None:
        return None
    if result.distribution.raw_probability is not None:
        return float(result.distribution.raw_probability)
    if result.distribution.selected and result.distribution.probabilities:
        selected = result.distribution.probabilities.get(result.distribution.selected)
        if selected is not None:
            return float(selected)
    if result.distribution.probabilities:
        return float(max(result.distribution.probabilities.values()))
    return None


# Provisional Jev rates inferred from the 2026-10-02 18-unit live eval note
# (~28.7k input tokens ≈ $0.0012 => ~$0.0418 / million tokens).
# Override per run; this is not an invoice.
PROVISIONAL_JEV_INPUT_USD_PER_MILLION = 0.04181
PROVISIONAL_JEV_OUTPUT_USD_PER_MILLION = 0.04181


def estimate_usage_cost(
    usage: Mapping[str, Any] | None,
    *,
    provider: str,
    input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
) -> dict[str, Any]:
    """Estimate dollar cost from token usage. Missing tokens stay null."""
    payload = dict(usage or {})
    if provider == "fake":
        return {
            "usage": payload,
            "provider": provider,
            "input_usd_per_million": 0.0,
            "output_usd_per_million": 0.0,
            "estimated_usd": 0.0,
            "pricing_source": "fake_provider_zero",
            "note": "fake provider has no billed usage",
        }

    input_rate = (
        PROVISIONAL_JEV_INPUT_USD_PER_MILLION
        if input_usd_per_million is None and provider == "jev"
        else input_usd_per_million
    )
    output_rate = (
        PROVISIONAL_JEV_OUTPUT_USD_PER_MILLION
        if output_usd_per_million is None and provider == "jev"
        else output_usd_per_million
    )
    input_tokens = _numeric_usage(payload, "input_tokens")
    output_tokens = _numeric_usage(payload, "output_tokens")
    estimated = None
    if input_rate is not None or output_rate is not None:
        estimated = 0.0
        if input_tokens is not None and input_rate is not None:
            estimated += input_tokens * input_rate / 1_000_000.0
        if output_tokens is not None and output_rate is not None:
            estimated += output_tokens * output_rate / 1_000_000.0
        if input_tokens is None and output_tokens is None:
            estimated = None
    return {
        "usage": payload,
        "provider": provider,
        "input_usd_per_million": input_rate,
        "output_usd_per_million": output_rate,
        "estimated_usd": estimated,
        "pricing_source": (
            "provisional_jev_2026-10-02_live_eval"
            if provider == "jev" and input_usd_per_million is None
            else "explicit_override"
        ),
        "note": (
            "estimate only; not an invoice. Pass --input-usd-per-million to override."
            if estimated is not None
            else "dollar estimate unavailable because token usage was not recorded"
        ),
    }


def _numeric_usage(usage: Mapping[str, Any], key: str) -> float | None:
    value = usage.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _selected_label(result: Any, *, noul_threshold: float) -> str | None:
    if result.status in {"failed", "none"}:
        return None
    if result.distribution is None:
        return None
    if result.distribution.selected:
        return str(result.distribution.selected)
    if not result.distribution.probabilities:
        return None
    return max(result.distribution.probabilities.items(), key=lambda item: item[1])[0]


def _noul_positive(result: Any, *, threshold: float) -> bool | None:
    if result.status in {"failed", "none"}:
        return None
    if result.status == "uncertain":
        return None
    dist = result.distribution
    if dist is None:
        return None
    if dist.selected in {"yes", "no"}:
        return dist.selected == "yes"
    if dist.raw_probability is not None:
        return float(dist.raw_probability) >= threshold
    yes_p = dist.probabilities.get("yes")
    if yes_p is None:
        return None
    return float(yes_p) >= threshold


def _macro_f1(pairs: Sequence[tuple[str, str]]) -> float:
    labels = sorted({gold for gold, _ in pairs} | {pred for _, pred in pairs})
    f1s: list[float] = []
    for label in labels:
        tp = sum(1 for gold, pred in pairs if gold == label and pred == label)
        fp = sum(1 for gold, pred in pairs if gold != label and pred == label)
        fn = sum(1 for gold, pred in pairs if gold == label and pred != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        if precision + recall == 0:
            f1s.append(0.0)
        else:
            f1s.append(2 * precision * recall / (precision + recall))
    return sum(f1s) / len(f1s) if f1s else 0.0


def _baseline_choice_agreement(
    records: Sequence[UnitClassificationRecord],
) -> tuple[float | None, int]:
    compared = 0
    agree = 0
    for record in records:
        mapped = map_choice_baseline(record.assertion_type)
        if mapped is None:
            continue
        choice = next(
            (r for r in record.results if r.question_id == STATEMENT_TYPE_QUESTION_ID),
            None,
        )
        if choice is None or choice.distribution is None:
            continue
        predicted = choice.distribution.selected
        if predicted is None:
            continue
        compared += 1
        if predicted == mapped:
            agree += 1
    if compared == 0:
        return None, 0
    return agree / compared, compared


def _baseline_subtype_agreement(
    records: Sequence[UnitClassificationRecord],
    *,
    noul_threshold: float,
) -> tuple[float | None, int]:
    compared = 0
    agree = 0
    for record in records:
        expected_noul = map_subtype_baseline(record.assertion_type)
        if expected_noul is None:
            continue
        result = next(
            (r for r in record.results if r.question_id == expected_noul),
            None,
        )
        if result is None:
            continue
        pred = _noul_positive(result, threshold=noul_threshold)
        if pred is None:
            continue
        compared += 1
        if pred:
            agree += 1
    if compared == 0:
        return None, 0
    return agree / compared, compared


def _percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def load_gold_labels(path: Any) -> list[GoldUnitLabel]:
    """Load gold labels from a JSON list or JSONL file."""
    from pathlib import Path
    import json

    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    labels: list[GoldUnitLabel] = []
    for row in rows:
        labels.append(
            GoldUnitLabel(
                unit_id=str(row["unit_id"]),
                statement_type=str(row["statement_type"]),
                noul_labels={
                    str(k): bool(v) for k, v in (row.get("noul_labels") or {}).items()
                },
                assertion_type=row.get("assertion_type"),
                notes=row.get("notes"),
            )
        )
    return labels
