"""Consistency and metamorphic tests for shadow decision classification.

Invariance families fail on choice-label flips, high-confidence binary flips,
and excessive probability movement. Contrast families (meaning-changing
transforms) record differences as observations, not failures.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_metrics import (
    choice_prediction,
    noul_prediction,
)
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.models.decision_models import UnitClassificationRecord
from research_analysis_layer.services.decision_model import DecisionModel

CONSISTENCY_SCHEMA_VERSION = "decision-consistency-report-v1"
PROBABILITY_TOLERANCE = 0.15
HIGH_CONFIDENCE = 0.70
FamilyKind = Literal["invariance", "contrast"]

CONTAMINATED_PREFIX = (
    "We recommend positioned for a flatter curve through mid-year. "
    "The 2s10s spread s: "
)
SEED_FORECAST = (
    "The 2s10s spread should compress to 30bp as front-end remains anchored "
    "by Fed patience while long-end faces term premium pressure from supply dynamics."
)
SEED_NEGATIVE_REC = (
    "We see no compelling reason to reposition for major USD moves in either direction."
)
SEED_COMPOUND = (
    "Sticky services inflation will delay cuts and therefore keep the long end under pressure."
)
NEIGHBOR_RECOMMENDATION = (
    "We recommend positioned for a flatter curve through mid-year."
)
BATCH_STABLE_FIELDS: tuple[str, ...] = (
    "statement_type",
    "is_forecast",
    "is_trade_or_action",
)

NEGATIVE_REC_VARIANTS = (
    SEED_NEGATIVE_REC,
    "Hold current USD positioning; do not initiate a major directional move.",
    "Maintain the current USD position rather than repositioning for major moves.",
    "Refrain from repositioning for major USD moves in either direction.",
    "Do not reposition for major USD moves in either direction.",
)


@dataclass(slots=True)
class ConsistencyCaseResult:
    family: str
    kind: FamilyKind
    case_id: str
    base_unit_id: str
    variant_unit_id: str
    base_text: str
    variant_text: str
    stable_fields: list[str]
    choice_label_flip: bool
    high_confidence_binary_flip: bool
    excessive_probability_movement: bool
    observations: list[str] = field(default_factory=list)
    failed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConsistencyReport:
    schema_version: str = CONSISTENCY_SCHEMA_VERSION
    probability_tolerance: float = PROBABILITY_TOLERANCE
    case_count: int = 0
    invariance_failures: int = 0
    contrast_observations: int = 0
    families: dict[str, dict[str, int]] = field(default_factory=dict)
    cases: list[ConsistencyCaseResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "probability_tolerance": self.probability_tolerance,
            "case_count": self.case_count,
            "invariance_failures": self.invariance_failures,
            "contrast_observations": self.contrast_observations,
            "families": self.families,
            "cases": [case.as_dict() for case in self.cases],
            "notes": list(self.notes),
        }


def _draft(unit_id: str, text: str, assertion_type: str | None) -> AssertionDraft:
    digest = hashlib.sha1(unit_id.encode("utf-8")).hexdigest()[:8]
    chunk_order = int(digest[:4], 16) % 10_000
    assertion_order = int(digest[4:], 16) % 10_000
    return AssertionDraft(
        chunk_order=chunk_order,
        assertion_order=assertion_order,
        assertion_type=assertion_type or "observation",
        text=text,
        normalized_text=normalize_text(text),
        summary_text=text,
    )


def _classify(
    model: DecisionModel,
    drafts: Sequence[AssertionDraft],
    *,
    batch_size: int,
    document_key: str,
) -> dict[str, UnitClassificationRecord]:
    classifier = ShadowDecisionClassifier(model, batch_size=batch_size)
    provenance = {
        f"chunk-{draft.chunk_order}:assertion-{draft.assertion_order}": {
            "seed_id": draft.summary_text[:40],
        }
        for draft in drafts
    }
    artifact = classifier.classify_assertions(
        drafts,
        document_key=document_key,
        provenance_by_unit=provenance,
    )
    by_text: dict[str, UnitClassificationRecord] = {}
    for record in artifact.units:
        by_text[record.source_text] = record
    return {record.unit_id: record for record in artifact.units} | by_text


def _by_source_text(
    classified: dict[str, UnitClassificationRecord],
) -> dict[str, UnitClassificationRecord]:
    unique: dict[str, UnitClassificationRecord] = {}
    for record in classified.values():
        if isinstance(record, UnitClassificationRecord):
            unique[record.source_text] = record
    return unique


def _record_for_text(
    classified: dict[str, UnitClassificationRecord],
    text: str,
) -> UnitClassificationRecord | None:
    if text in classified:
        return classified[text]
    for record in classified.values():
        if record.source_text == text:
            return record
    return None


def _compare_pair(
    *,
    family: str,
    kind: FamilyKind,
    case_id: str,
    base: UnitClassificationRecord,
    variant: UnitClassificationRecord,
    stable_fields: Sequence[str],
) -> ConsistencyCaseResult:
    base_choice, base_choice_p = choice_prediction(base)
    var_choice, var_choice_p = choice_prediction(variant)
    choice_flip = (
        base_choice is not None
        and var_choice is not None
        and base_choice != var_choice
    )
    binary_flip = False
    excessive = False
    observations: list[str] = []
    if choice_flip:
        observations.append(
            f"statement_type {base_choice!r} -> {var_choice!r} "
            f"({_fmt_p(base_choice_p)} -> {_fmt_p(var_choice_p)})"
        )
    if _moved(base_choice_p, var_choice_p):
        excessive = True
        observations.append(
            f"statement_type probability moved {_fmt_p(base_choice_p)} -> {_fmt_p(var_choice_p)}"
        )

    for field_name in stable_fields:
        if field_name == "statement_type":
            continue
        base_noul, base_p = noul_prediction(base, field_name)
        var_noul, var_p = noul_prediction(variant, field_name)
        if (
            base_noul is not None
            and var_noul is not None
            and base_noul != var_noul
            and max(_conf(base_p), _conf(var_p)) >= HIGH_CONFIDENCE
        ):
            binary_flip = True
            observations.append(
                f"{field_name} {base_noul} -> {var_noul} "
                f"({_fmt_p(base_p)} -> {_fmt_p(var_p)})"
            )
        if _moved(base_p, var_p):
            excessive = True
            observations.append(
                f"{field_name} probability moved {_fmt_p(base_p)} -> {_fmt_p(var_p)}"
            )

    failed = kind == "invariance" and (choice_flip or binary_flip or excessive)
    return ConsistencyCaseResult(
        family=family,
        kind=kind,
        case_id=case_id,
        base_unit_id=base.unit_id,
        variant_unit_id=variant.unit_id,
        base_text=base.source_text,
        variant_text=variant.source_text,
        stable_fields=list(stable_fields),
        choice_label_flip=choice_flip,
        high_confidence_binary_flip=binary_flip,
        excessive_probability_movement=excessive,
        observations=observations,
        failed=failed,
    )


def _conf(probability: float | None) -> float:
    if probability is None:
        return 0.0
    return max(probability, 1.0 - probability)


def _moved(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) > PROBABILITY_TOLERANCE


def _fmt_p(value: float | None) -> str:
    return "none" if value is None else f"{value:.2f}"


def _family_summary(cases: Sequence[ConsistencyCaseResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for case in cases:
        bucket = summary.setdefault(
            case.family,
            {"cases": 0, "failures": 0, "choice_flips": 0, "binary_flips": 0},
        )
        bucket["cases"] += 1
        bucket["failures"] += int(case.failed)
        bucket["choice_flips"] += int(case.choice_label_flip)
        bucket["binary_flips"] += int(case.high_confidence_binary_flip)
    return summary


def run_context_isolation(
    model: DecisionModel,
    *,
    sentence: str = SEED_FORECAST,
    assertion_type: str = "forecast",
) -> list[ConsistencyCaseResult]:
    prefixes = (
        CONTAMINATED_PREFIX,
        "## Positioning\n\n",
        "Neighboring sentence about an unrelated trade. ",
    )
    drafts = [_draft("ctx-base", sentence, assertion_type)]
    for index, prefix in enumerate(prefixes):
        drafts.append(_draft(f"ctx-var-{index}", prefix + sentence, assertion_type))
    classified = _classify(model, drafts, batch_size=4, document_key="consistency-context")
    base = _record_for_text(classified, sentence)
    if base is None:
        return []
    results: list[ConsistencyCaseResult] = []
    for index, prefix in enumerate(prefixes):
        variant = _record_for_text(classified, prefix + sentence)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="context_isolation",
                kind="invariance",
                case_id=f"context-isolation-{index}",
                base=base,
                variant=variant,
                stable_fields=("statement_type", "is_forecast", "is_trade_or_action"),
            )
        )
    return results


def run_negative_recommendation_equivalence(
    model: DecisionModel,
    *,
    assertion_type: str = "trade_claim",
) -> list[ConsistencyCaseResult]:
    drafts = [
        _draft(f"neg-{index}", text, assertion_type)
        for index, text in enumerate(NEGATIVE_REC_VARIANTS)
    ]
    classified = _classify(
        model, drafts, batch_size=8, document_key="consistency-negative-rec"
    )
    base = _record_for_text(classified, NEGATIVE_REC_VARIANTS[0])
    if base is None:
        return []
    results: list[ConsistencyCaseResult] = []
    for index, text in enumerate(NEGATIVE_REC_VARIANTS[1:], start=1):
        variant = _record_for_text(classified, text)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="negative_recommendation_equivalence",
                kind="invariance",
                case_id=f"negative-rec-{index}",
                base=base,
                variant=variant,
                stable_fields=("statement_type", "is_trade_or_action"),
            )
        )
    return results


def run_compound_decomposition(
    model: DecisionModel,
    *,
    sentence: str = SEED_COMPOUND,
    assertion_type: str = "causal_claim",
) -> list[ConsistencyCaseResult]:
    clauses = _split_clauses(sentence)
    drafts = [_draft("compound-base", sentence, assertion_type)]
    for index, clause in enumerate(clauses):
        drafts.append(_draft(f"compound-clause-{index}", clause, assertion_type))
    classified = _classify(
        model, drafts, batch_size=4, document_key="consistency-compound"
    )
    base = _record_for_text(classified, sentence)
    if base is None:
        return []
    results: list[ConsistencyCaseResult] = []
    for index, clause in enumerate(clauses):
        variant = _record_for_text(classified, clause)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="compound_decomposition",
                kind="contrast",
                case_id=f"compound-{index}",
                base=base,
                variant=variant,
                stable_fields=("statement_type", "is_forecast", "is_causal"),
            )
        )
    return results


def _split_clauses(sentence: str) -> list[str]:
    parts = re.split(r"\s+(?:and therefore|as|while)\s+", sentence)
    clauses = [part.strip(" ,.") + "." for part in parts if len(part.strip()) > 12]
    return clauses if len(clauses) >= 2 else [sentence]


def run_formatting_invariance(
    model: DecisionModel,
    *,
    sentence: str = SEED_FORECAST,
    assertion_type: str = "forecast",
) -> list[ConsistencyCaseResult]:
    variants = (
        "  " + sentence.replace(" ", "  "),
        f"- {sentence}",
        f"## Outlook\n{sentence}",
        sentence.rstrip(".") + "!!!",
    )
    drafts = [_draft("fmt-base", sentence, assertion_type)]
    for index, text in enumerate(variants):
        drafts.append(_draft(f"fmt-{index}", text, assertion_type))
    classified = _classify(model, drafts, batch_size=4, document_key="consistency-format")
    base = _record_for_text(classified, sentence)
    if base is None:
        return []
    results: list[ConsistencyCaseResult] = []
    for index, text in enumerate(variants):
        variant = _record_for_text(classified, text)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="formatting_invariance",
                kind="invariance",
                case_id=f"formatting-{index}",
                base=base,
                variant=variant,
                stable_fields=("statement_type", "is_forecast"),
            )
        )
    return results


def run_batch_invariance(
    model: DecisionModel,
    drafts: Sequence[AssertionDraft],
    *,
    sizes: Sequence[int] = (1, 2, 4, 8),
) -> list[ConsistencyCaseResult]:
    """Batch size, neighbor, and order must not change labels of the same unit."""
    results: list[ConsistencyCaseResult] = []
    results.extend(_batch_size_invariance(model, drafts, sizes=sizes))
    results.extend(_batch_order_invariance(model, drafts))
    results.extend(_batch_neighbor_invariance(model))
    return results


def _batch_size_invariance(
    model: DecisionModel,
    drafts: Sequence[AssertionDraft],
    *,
    sizes: Sequence[int],
) -> list[ConsistencyCaseResult]:
    if not drafts:
        return []
    by_size: dict[int, dict[str, UnitClassificationRecord]] = {}
    for size in sizes:
        by_size[size] = _by_source_text(
            _classify(
                model,
                drafts,
                batch_size=max(1, size),
                document_key=f"consistency-batch-{size}",
            )
        )
    base_size = sizes[0]
    results: list[ConsistencyCaseResult] = []
    for text, base in by_size[base_size].items():
        for size in sizes[1:]:
            variant = by_size[size].get(text)
            if variant is None:
                continue
            results.append(
                _compare_pair(
                    family="batch_invariance",
                    kind="invariance",
                    case_id=f"batch-size-{base_size}-vs-{size}-{base.unit_id}",
                    base=base,
                    variant=variant,
                    stable_fields=BATCH_STABLE_FIELDS,
                )
            )
    return results


def _batch_order_invariance(
    model: DecisionModel,
    drafts: Sequence[AssertionDraft],
    *,
    batch_size: int = 4,
) -> list[ConsistencyCaseResult]:
    ordered = list(drafts)
    if len(ordered) < 2:
        return []
    forward = _by_source_text(
        _classify(
            model,
            ordered,
            batch_size=max(1, batch_size),
            document_key="consistency-order-fwd",
        )
    )
    reversed_order = _by_source_text(
        _classify(
            model,
            list(reversed(ordered)),
            batch_size=max(1, batch_size),
            document_key="consistency-order-rev",
        )
    )
    results: list[ConsistencyCaseResult] = []
    for text, base in forward.items():
        variant = reversed_order.get(text)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="batch_invariance",
                kind="invariance",
                case_id=f"batch-order-{base.unit_id}",
                base=base,
                variant=variant,
                stable_fields=BATCH_STABLE_FIELDS,
            )
        )
    return results


def _batch_neighbor_invariance(model: DecisionModel) -> list[ConsistencyCaseResult]:
    target = _draft("nbr-target", SEED_FORECAST, "forecast")
    neighbor = _draft("nbr-rec", NEIGHBOR_RECOMMENDATION, "trade_claim")
    solo = _by_source_text(
        _classify(
            model, [target], batch_size=1, document_key="consistency-neighbor-solo"
        )
    )
    right = _by_source_text(
        _classify(
            model,
            [target, neighbor],
            batch_size=2,
            document_key="consistency-neighbor-right",
        )
    )
    left = _by_source_text(
        _classify(
            model,
            [neighbor, target],
            batch_size=2,
            document_key="consistency-neighbor-left",
        )
    )
    base = solo.get(SEED_FORECAST)
    if base is None:
        return []
    results: list[ConsistencyCaseResult] = []
    for name, group in (("right", right), ("left", left)):
        variant = group.get(SEED_FORECAST)
        if variant is None:
            continue
        results.append(
            _compare_pair(
                family="batch_invariance",
                kind="invariance",
                case_id=f"batch-neighbor-solo-vs-{name}",
                base=base,
                variant=variant,
                stable_fields=BATCH_STABLE_FIELDS,
            )
        )
    return results


def run_repeatability(
    model: DecisionModel,
    drafts: Sequence[AssertionDraft],
    *,
    runs: int = 3,
) -> list[ConsistencyCaseResult]:
    if not drafts or runs < 2:
        return []
    snapshots: list[dict[str, UnitClassificationRecord]] = []
    for index in range(runs):
        classified = _classify(
            model, drafts, batch_size=4, document_key=f"consistency-repeat-{index}"
        )
        snapshots.append(_by_source_text(classified))
    results: list[ConsistencyCaseResult] = []
    for text, base in snapshots[0].items():
        for run_index, snapshot in enumerate(snapshots[1:], start=1):
            variant = snapshot.get(text)
            if variant is None:
                continue
            results.append(
                _compare_pair(
                    family="repeatability",
                    kind="invariance",
                    case_id=f"repeat-0-vs-{run_index}-{base.unit_id}",
                    base=base,
                    variant=variant,
                    stable_fields=("statement_type", "is_forecast"),
                )
            )
    return results


def run_consistency_suite(
    model: DecisionModel,
    *,
    fixture_drafts: Sequence[AssertionDraft] = (),
    repeatability_runs: int = 3,
) -> ConsistencyReport:
    cases: list[ConsistencyCaseResult] = []
    cases.extend(run_context_isolation(model))
    cases.extend(run_negative_recommendation_equivalence(model))
    cases.extend(run_compound_decomposition(model))
    cases.extend(run_formatting_invariance(model))
    batch_drafts = list(fixture_drafts[:8]) or [
        _draft("batch-seed", SEED_FORECAST, "forecast")
    ]
    cases.extend(run_batch_invariance(model, batch_drafts))
    cases.extend(
        run_repeatability(model, batch_drafts[:4], runs=repeatability_runs)
    )
    failures = sum(case.failed for case in cases)
    contrast_obs = sum(
        1
        for case in cases
        if case.kind == "contrast" and case.observations
    )
    notes = [
        "choice-label flips, high-confidence binary flips, and probability "
        f"moves > {PROBABILITY_TOLERANCE:.2f} are reported separately",
        "compound_decomposition is a contrast family: differences are observations",
        "fake provider choice labels follow assertion_type, so wording-only "
        "families need --provider jev to expose model sensitivity",
        "batch_invariance covers sizes 1/2/4/8 plus neighbor and order changes",
    ]
    return ConsistencyReport(
        case_count=len(cases),
        invariance_failures=failures,
        contrast_observations=contrast_obs,
        families=_family_summary(cases),
        cases=cases,
        notes=notes,
    )
