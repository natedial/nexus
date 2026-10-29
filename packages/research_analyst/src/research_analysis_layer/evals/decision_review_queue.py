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

QUEUE_SCHEMA_VERSION = "decision-review-queue-v2"
CONTEXT_CLIP_CHARS = 240
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
    silver_rules: list[str] = field(default_factory=list)
    suggested_labels: dict[str, str | bool] = field(default_factory=dict)
    questions: list[str] = field(default_factory=list)
    reviewed_text: str | None = None
    stored_model_input: str | None = None
    surrounding_context: str | None = None
    model_noul: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cluster_id(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    key = " ".join(normalized.split()[:12])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _gold_by_id(gold: Sequence[GoldUnitLabel]) -> dict[str, GoldUnitLabel]:
    return {item.unit_id: item for item in gold}


def _clip(text: str, limit: int = CONTEXT_CLIP_CHARS) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def stored_input_diff(reviewed_text: str, stored_model_input: str) -> dict[str, Any]:
    """Split stored model input into prefix / reviewed sentence / suffix."""
    if reviewed_text == stored_model_input:
        return {
            "identical": True,
            "prefix": "",
            "sentence": reviewed_text,
            "suffix": "",
            "stored": stored_model_input,
        }
    if reviewed_text and reviewed_text in stored_model_input:
        start = stored_model_input.index(reviewed_text)
        return {
            "identical": False,
            "prefix": stored_model_input[:start],
            "sentence": reviewed_text,
            "suffix": stored_model_input[start + len(reviewed_text) :],
            "stored": stored_model_input,
        }
    return {
        "identical": False,
        "prefix": "",
        "sentence": reviewed_text,
        "suffix": "",
        "stored": stored_model_input,
    }


def _surrounding_context(
    records: Sequence[UnitClassificationRecord],
    current: UnitClassificationRecord,
) -> str | None:
    same = [
        record
        for record in records
        if record.document_key == current.document_key
    ]
    same.sort(key=lambda record: record.unit_id)
    idx = next(
        (
            index
            for index, record in enumerate(same)
            if record.unit_id == current.unit_id
        ),
        None,
    )
    parts: list[str] = []
    title = (current.provenance or {}).get("doc_section_title")
    if title:
        parts.append(f"Section: {title}")
    if idx is not None and idx > 0:
        parts.append(f"Previous: {_clip(same[idx - 1].source_text)}")
    if idx is not None and idx + 1 < len(same):
        parts.append(f"Next: {_clip(same[idx + 1].source_text)}")
    return "\n\n".join(parts) if parts else None


def _model_noul_summary(record: UnitClassificationRecord) -> dict[str, str]:
    summary: dict[str, str] = {}
    for noul_id in sorted(LOAD_BEARING_NOULS):
        pred, pred_p = noul_prediction(record, noul_id)
        if pred is None:
            continue
        token = "yes" if pred else "no"
        if pred_p is None:
            summary[noul_id] = token
        else:
            summary[noul_id] = f"{token} (p={pred_p:.2f})"
    return summary


def _silver_rule_names(silver_row: Any | None) -> list[str]:
    if silver_row is None:
        return []
    names: list[str] = []
    for hit in silver_row.hits:
        if hit.confidence_tier != "high":
            continue
        names.append(f"{hit.rule_id}:{hit.field}={hit.value}")
    return names


def _scope_texts(
    record: UnitClassificationRecord,
    gold_row: GoldUnitLabel | None,
) -> tuple[str, str]:
    reviewed = record.source_text
    stored = record.source_text
    if gold_row is not None:
        if gold_row.reviewed_text:
            reviewed = gold_row.reviewed_text
        if gold_row.stored_model_input:
            stored = gold_row.stored_model_input
    return reviewed, stored


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
        reviewed_text, stored_input = _scope_texts(record, gold_row)
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
                silver_rules=_silver_rule_names(silver_row),
                suggested_labels=suggested,
                questions=questions or ["Does the model label match the intended meaning?"],
                reviewed_text=reviewed_text,
                stored_model_input=stored_input,
                surrounding_context=_surrounding_context(records, record),
                model_noul=_model_noul_summary(record),
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
            silver_row = silver_by_unit.get(record.unit_id)
            reviewed_text, stored_input = _scope_texts(record, None)
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
                    silver_labels=dict(silver_row.included_labels) if silver_row else {},
                    silver_rules=_silver_rule_names(silver_row),
                    questions=["Random audit: is the current label correct?"],
                    reviewed_text=reviewed_text,
                    stored_model_input=stored_input,
                    surrounding_context=_surrounding_context(records, record),
                    model_noul=_model_noul_summary(record),
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


def _details_block(summary: str, body_lines: Sequence[str]) -> list[str]:
    return [
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        *body_lines,
        "",
        "</details>",
        "",
    ]


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
        sentence = item.reviewed_text or item.source_text
        stored = item.stored_model_input or item.source_text
        diff = stored_input_diff(sentence, stored)
        lines.extend(
            [
                f"## {index}. `{item.document_id or 'unknown'}` / `{item.unit_id}`",
                "",
                f"Priority {item.priority}: {', '.join(item.reasons)}",
                "",
                "### Sentence",
                "",
                f"> {sentence}",
                "",
            ]
        )
        context_body = (
            item.surrounding_context.split("\n\n")
            if item.surrounding_context
            else ["No neighboring units or section title were available."]
        )
        context_lines: list[str] = []
        for part in context_body:
            context_lines.extend([part, ""])
        if context_lines and context_lines[-1] == "":
            context_lines.pop()
        lines.extend(_details_block("Surrounding context", context_lines))
        if diff["identical"]:
            stored_lines = ["Identical to the sentence above."]
        else:
            stored_lines = []
            if diff["prefix"].strip():
                stored_lines.extend(
                    [
                        "**Extra prefix (not in review scope):**",
                        "",
                        f"> {diff['prefix'].rstrip()}",
                        "",
                    ]
                )
            stored_lines.extend(
                ["**Reviewed sentence:**", "", f"> {diff['sentence']}", ""]
            )
            if diff["suffix"].strip():
                stored_lines.extend(
                    [
                        "**Extra suffix (not in review scope):**",
                        "",
                        f"> {diff['suffix'].lstrip()}",
                        "",
                    ]
                )
            if not diff["prefix"] and not diff["suffix"] and diff["stored"] != sentence:
                stored_lines.extend(
                    [
                        "**Stored model input:**",
                        "",
                        f"> {diff['stored']}",
                        "",
                    ]
                )
            if stored_lines and stored_lines[-1] == "":
                stored_lines.pop()
        lines.extend(_details_block("Stored model input", stored_lines))
        noul_bits = ", ".join(
            f"{name}={value}" for name, value in item.model_noul.items()
        ) or "none"
        lines.extend(
            [
                "### Model / gold / silver",
                "",
                f"- Model statement_type: `{item.model_statement_type}` "
                f"(p={item.model_probability if item.model_probability is not None else 'n/a'})",
                f"- Model load-bearing Nouls: `{noul_bits}`",
                f"- Gold statement_type: `{item.gold_statement_type or 'none'}`",
                f"- Silver labels: `{item.silver_labels or {}}`",
                f"- Silver rules: `{item.silver_rules or []}`",
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
