"""Bounded review-queue construction for decision-model evaluation."""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from research_analysis_layer.evals.decision_consistency import ConsistencyCaseResult
from research_analysis_layer.evals.decision_metrics import (
    GoldUnitLabel,
    choice_prediction,
    noul_prediction,
)
from research_analysis_layer.evals.decision_silver import SilverAgreementReport
from research_analysis_layer.models.decision_models import UnitClassificationRecord

QUEUE_SCHEMA_VERSION = "decision-review-queue-v1"
HIGH_CONFIDENCE = 0.70
NEAR_THRESHOLD = 0.10
LOAD_BEARING_TYPES = frozenset({"recommendation"})
LOAD_BEARING_NOULS = frozenset({"is_trade_or_action", "is_forecast", "is_causal"})

PRIORITY_RULES: tuple[tuple[int, str], ...] = (
    (1, "high_confidence_gold_disagreement"),
    (2, "load_bearing_disagreement"),
    (3, "consistency_failure"),
    (4, "silver_or_deterministic_disagreement"),
    (5, "underrepresented_taxonomy"),
    (6, "near_routing_threshold"),
    (7, "random_audit"),
)


@dataclass(slots=True)
class ReviewCandidate:
    unit_id: str
    document_id: str | None
    source_text: str
    priority: int
    reasons: list[str]
    cluster_id: str
    representative: bool = True
    gold_statement_type: str | None = None
    model_statement_type: str | None = None
    model_probability: float | None = None
    silver_labels: dict[str, str | bool] = field(default_factory=dict)
    suggested_labels: dict[str, str | bool] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cluster_id(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    key = " ".join(normalized.split()[:12])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _gold_by_id(gold: Sequence[GoldUnitLabel]) -> dict[str, GoldUnitLabel]:
    return {item.unit_id: item for item in gold}


def build_review_queue(
    records: Sequence[UnitClassificationRecord],
    *,
    gold_labels: Sequence[GoldUnitLabel] = (),
    gold_document_id: str | None = None,
    silver: SilverAgreementReport | None = None,
    consistency_cases: Sequence[ConsistencyCaseResult] = (),
    packet_size: int = 20,
    rng: random.Random | None = None,
) -> list[ReviewCandidate]:
    """Select a bounded, de-duplicated review packet using explicit priorities."""
    if packet_size < 1:
        raise ValueError("packet_size must be >= 1")
    rng = rng or random.Random(0)
    gold = _gold_by_id([label for label in gold_labels if label.document_id is None])
    gold_by_document = {
        (label.document_id, label.unit_id): label
        for label in gold_labels
        if label.document_id
    }
    silver_by_unit = {
        record.unit_id: record
        for record in (silver.records if silver is not None else [])
    }
    silver_disagreements = {
        (item.unit_id, item.field)
        for item in (silver.disagreements if silver is not None else [])
    }
    consistency_by_text = {
        case.base_text: case for case in consistency_cases if case.failed
    }
    consistency_by_text.update(
        {case.variant_text: case for case in consistency_cases if case.failed}
    )

    type_counts: dict[str, int] = {}
    for label in gold_labels:
        type_counts[label.statement_type] = type_counts.get(label.statement_type, 0) + 1
    rare_types = {
        name for name, count in type_counts.items() if count <= 2
    } if type_counts else set()

    candidates: list[ReviewCandidate] = []
    already_reviewed: set[tuple[str | None, str]] = set()
    for record in records:
        choice, choice_p = choice_prediction(record)
        gold_row = None
        if record.document_key:
            gold_row = gold_by_document.get((record.document_key, record.unit_id))
        if gold_row is None and (
            gold_document_id is None or record.document_key == gold_document_id
        ):
            gold_row = gold.get(record.unit_id)
        if gold_row is not None and gold_row.document_id:
            # Already-agreed review (possibly partial). Do not present again.
            already_reviewed.add((record.document_key, record.unit_id))
            continue
        reasons: list[str] = []
        questions: list[str] = []
        priority = 99
        suggested: dict[str, str | bool] = {}

        if gold_row is not None and choice is not None and choice != gold_row.statement_type:
            if (choice_p or 0.0) >= HIGH_CONFIDENCE:
                priority = min(priority, 1)
                reasons.append("high_confidence_gold_disagreement")
            if (
                gold_row.statement_type in LOAD_BEARING_TYPES
                or choice in LOAD_BEARING_TYPES
            ):
                priority = min(priority, 2)
                reasons.append("load_bearing_disagreement")
            questions.append("What is the primary statement type?")
            suggested["statement_type"] = gold_row.statement_type

        for noul_id in LOAD_BEARING_NOULS:
            pred, pred_p = noul_prediction(record, noul_id)
            gold_noul = None if gold_row is None else gold_row.noul_labels.get(noul_id)
            if gold_noul is not None and pred is not None and pred != gold_noul:
                priority = min(priority, 2)
                reasons.append("load_bearing_disagreement")
                questions.append(f"Is {noul_id} present?")
                suggested[noul_id] = gold_noul
            if pred_p is not None and abs(pred_p - 0.5) <= NEAR_THRESHOLD:
                priority = min(priority, 6)
                reasons.append("near_routing_threshold")

        failed_case = consistency_by_text.get(record.source_text)
        if failed_case is not None:
            priority = min(priority, 3)
            reasons.append("consistency_failure")
            questions.append(f"Inspect {failed_case.family} sensitivity")

        silver_row = silver_by_unit.get(record.unit_id)
        silver_labels = dict(silver_row.included_labels) if silver_row else {}
        if any(unit_id == record.unit_id for unit_id, _field in silver_disagreements):
            priority = min(priority, 4)
            reasons.append("silver_or_deterministic_disagreement")
        if (
            record.assertion_type
            and choice is not None
            and record.assertion_type == "trade_claim"
            and choice != "recommendation"
        ):
            priority = min(priority, 4)
            reasons.append("silver_or_deterministic_disagreement")

        if gold_row is not None and gold_row.statement_type in rare_types:
            priority = min(priority, 5)
            reasons.append("underrepresented_taxonomy")

        if not reasons:
            continue
        candidates.append(
            ReviewCandidate(
                unit_id=record.unit_id,
                document_id=record.document_key,
                source_text=record.source_text,
                priority=priority,
                reasons=sorted(set(reasons)),
                cluster_id=_cluster_id(record.source_text),
                gold_statement_type=None if gold_row is None else gold_row.statement_type,
                model_statement_type=choice,
                model_probability=choice_p,
                silver_labels=silver_labels,
                suggested_labels=suggested,
                questions=questions or ["Does the model label match the intended meaning?"],
            )
        )

    audit_n = min(packet_size, max(1, math.ceil(0.01 * max(1, len(records)))))
    unused = [
        record
        for record in records
        if (record.document_key, record.unit_id) not in already_reviewed
        and record.unit_id not in {item.unit_id for item in candidates}
    ]
    if unused:
        sample = unused[:]
        rng.shuffle(sample)
        for record in sample[:audit_n]:
            choice, choice_p = choice_prediction(record)
            candidates.append(
                ReviewCandidate(
                    unit_id=record.unit_id,
                    document_id=record.document_key,
                    source_text=record.source_text,
                    priority=7,
                    reasons=["random_audit"],
                    cluster_id=_cluster_id(record.source_text),
                    model_statement_type=choice,
                    model_probability=choice_p,
                    questions=["Random audit: is the current label correct?"],
                )
            )

    candidates.sort(key=lambda item: (item.priority, item.unit_id))
    selected: list[ReviewCandidate] = []
    seen_clusters: set[str] = set()
    for item in candidates:
        if item.cluster_id in seen_clusters:
            continue
        item.representative = True
        selected.append(item)
        seen_clusters.add(item.cluster_id)
        if len(selected) >= packet_size:
            break
    return selected


def review_packet_markdown(candidates: Sequence[ReviewCandidate]) -> str:
    """One-screen-per-case markdown packet. Suggestions are marked as proposals."""
    lines = [
        "# Decision-model review packet",
        "",
        "Agent proposals are suggestions only. Do not treat them as gold.",
        f"Cases: {len(candidates)} (cap 20 unless overridden).",
        "",
    ]
    for index, item in enumerate(candidates, start=1):
        lines.extend(
            [
                f"## {index}. `{item.document_id or 'unknown'}` / `{item.unit_id}`",
                "",
                f"Priority {item.priority}: {', '.join(item.reasons)}",
                "",
                "### Sentence",
                "",
                f"> {item.source_text}",
                "",
                "### Model / gold / silver",
                "",
                f"- Model statement_type: `{item.model_statement_type}` "
                f"(p={item.model_probability if item.model_probability is not None else 'n/a'})",
                f"- Gold statement_type: `{item.gold_statement_type or 'none'}`",
                f"- Silver labels: `{item.silver_labels or {}}`",
                f"- Suggested labels (agent proposal): `{item.suggested_labels or {}}`",
                "",
                "### Questions",
                "",
            ]
        )
        for question in item.questions:
            lines.append(f"- {question}")
        lines.extend(["", "Outcome: approve / edit / defer", "", "Rationale:", "", "---", ""])
    return "\n".join(lines)
