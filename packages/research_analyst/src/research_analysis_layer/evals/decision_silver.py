"""High-precision, rule-attributed silver labels for decision-model evals.

Silver labels are never merged into gold. Conflicted or low-confidence hits
are excluded from silver agreement metrics and may become review candidates.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

from research_analysis_layer.evals.decision_metrics import (
    choice_prediction,
    noul_prediction,
)
from research_analysis_layer.models.decision_models import (
    SUBTYPE_NOUL_IDS,
    SUPPORT_NOUL_IDS,
    UnitClassificationRecord,
)

SILVER_RULE_VERSION = "decision-silver-rules-v1"
NOUL_QUESTION_IDS: tuple[str, ...] = (*SUBTYPE_NOUL_IDS, *SUPPORT_NOUL_IDS)
ConfidenceTier = Literal["high", "low"]

_RECOMMENDATION_HIGH = (
    re.compile(r"(?i)\bwe recommend\b"),
    re.compile(r"(?i)\bno compelling reason to (?:reposition|change (?:our |the )?positioning)\b"),
    re.compile(r"(?i)\bdo not reposition\b"),
    re.compile(r"(?i)\brefrain from\b"),
    re.compile(r"(?i)\bmaintain (?:the )?(?:current )?.{0,20}?\b(?:positioning|position|overweight|underweight)\b"),
    re.compile(r"(?i)\bhold (?:the )?(?:current )?.{0,20}?\b(?:positioning|position)\b"),
    re.compile(r"(?i)\boverweighting\b"),
    re.compile(r"(?i)\bunderweighting\b"),
)
_EVIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("percent", re.compile(r"\b\d+(?:\.\d+)?%")),
    ("basis_points", re.compile(r"(?i)\b\d+(?:\.\d+)?\s*(?:bp|basis points?)\b")),
    ("named_release", re.compile(r"(?i)\b(?:bls|cpi|pce|nfp|payrolls|employment report)\b")),
    ("citation", re.compile(r"(?i)\baccording to\b")),
    ("quotation", re.compile(r"[“\"][^”\"]{8,}[”\"]")),
    ("figure_ref", re.compile(r"(?i)\b(?:figure|chart|table)\s+\d+\b")),
    ("count_move", re.compile(r"(?i)\b(?:printed|rose|fell|revised)\b[^.]{0,40}\d")),
)
_METHODOLOGY_HIGH = (
    re.compile(r"(?i)\bthis section summarizes\b"),
    re.compile(r"(?i)\bsample construction\b"),
    re.compile(r"(?i)\bdata sources used\b"),
    re.compile(r"(?i)\bplease see the appendix\b"),
    re.compile(r"(?i)\bfor illustrative purposes\b"),
    re.compile(r"(?i)\bdefinitions of the variables\b"),
)


@dataclass(slots=True)
class SilverHit:
    rule_id: str
    field: str
    value: str | bool
    confidence_tier: ConfidenceTier
    evidence: str
    rule_version: str = SILVER_RULE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SilverUnitRecord:
    unit_id: str
    document_id: str | None
    source_text: str
    assertion_type: str | None
    hits: list[SilverHit] = field(default_factory=list)
    conflicting_rule_ids: list[str] = field(default_factory=list)
    excluded_from_metrics: bool = False
    included_labels: dict[str, str | bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["hits"] = [hit.as_dict() for hit in self.hits]
        return payload


@dataclass(slots=True)
class SilverDisagreement:
    unit_id: str
    field: str
    silver_value: str | bool
    model_value: str | bool | None
    rule_ids: list[str]
    model_probability: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SilverAgreementReport:
    schema_version: str = "decision-silver-agreement-v1"
    rule_version: str = SILVER_RULE_VERSION
    unit_count: int = 0
    included_label_count: int = 0
    excluded_conflict_count: int = 0
    excluded_low_confidence_count: int = 0
    compared: int = 0
    agreements: int = 0
    agreement_rate: float | None = None
    disagreements: list[SilverDisagreement] = field(default_factory=list)
    records: list[SilverUnitRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rule_version": self.rule_version,
            "unit_count": self.unit_count,
            "included_label_count": self.included_label_count,
            "excluded_conflict_count": self.excluded_conflict_count,
            "excluded_low_confidence_count": self.excluded_low_confidence_count,
            "compared": self.compared,
            "agreements": self.agreements,
            "agreement_rate": self.agreement_rate,
            "disagreements": [item.as_dict() for item in self.disagreements],
            "records": [item.as_dict() for item in self.records],
            "notes": list(self.notes),
        }


def silver_hits_for_unit(
    *,
    text: str,
    assertion_type: str | None,
    unit_id: str = "",
) -> list[SilverHit]:
    """Return rule hits for one unit. Does not resolve conflicts."""
    del unit_id
    hits: list[SilverHit] = []
    if assertion_type == "open_question":
        hits.append(
            SilverHit(
                rule_id="open_question_to_question",
                field="statement_type",
                value="question",
                confidence_tier="high",
                evidence="deterministic assertion_type=open_question",
            )
        )
    if assertion_type == "trade_claim":
        hits.append(
            SilverHit(
                rule_id="trade_claim_to_recommendation",
                field="statement_type",
                value="recommendation",
                confidence_tier="high",
                evidence="deterministic assertion_type=trade_claim",
            )
        )
        hits.append(
            SilverHit(
                rule_id="trade_claim_to_recommendation",
                field="is_trade_or_action",
                value=True,
                confidence_tier="high",
                evidence="deterministic assertion_type=trade_claim",
            )
        )

    rec_matches = [pat.pattern for pat in _RECOMMENDATION_HIGH if pat.search(text)]
    if rec_matches:
        evidence = "recommendation language: " + ", ".join(rec_matches[:3])
        hits.append(
            SilverHit(
                rule_id="explicit_recommendation_language",
                field="statement_type",
                value="recommendation",
                confidence_tier="high",
                evidence=evidence,
            )
        )
        hits.append(
            SilverHit(
                rule_id="explicit_recommendation_language",
                field="is_trade_or_action",
                value=True,
                confidence_tier="high",
                evidence=evidence,
            )
        )

    evidence_hits = [name for name, pat in _EVIDENCE_PATTERNS if pat.search(text)]
    if evidence_hits:
        strong = {
            "named_release",
            "quotation",
            "figure_ref",
            "citation",
            "basis_points",
        }
        tier: ConfidenceTier = (
            "high"
            if len(evidence_hits) >= 2 or any(name in strong for name in evidence_hits)
            else "low"
        )
        hits.append(
            SilverHit(
                rule_id="verifiable_evidence_markers",
                field="contains_verifiable_evidence",
                value=True,
                confidence_tier=tier,
                evidence="markers: " + ", ".join(evidence_hits),
            )
        )

    method_matches = [pat.pattern for pat in _METHODOLOGY_HIGH if pat.search(text)]
    if method_matches:
        hits.append(
            SilverHit(
                rule_id="methodology_boilerplate",
                field="statement_type",
                value="background_methodology",
                confidence_tier="high",
                evidence="boilerplate: " + ", ".join(method_matches[:3]),
            )
        )
    return hits


def build_silver_record(
    *,
    unit_id: str,
    text: str,
    assertion_type: str | None,
    document_id: str | None = None,
) -> SilverUnitRecord:
    hits = silver_hits_for_unit(
        text=text, assertion_type=assertion_type, unit_id=unit_id
    )
    by_field: dict[str, list[SilverHit]] = {}
    for hit in hits:
        by_field.setdefault(hit.field, []).append(hit)

    conflicting: list[str] = []
    included: dict[str, str | bool] = {}
    excluded = False
    low_only = True
    for field_name, field_hits in by_field.items():
        values = {hit.value for hit in field_hits}
        if len(values) > 1:
            excluded = True
            conflicting.extend(sorted({hit.rule_id for hit in field_hits}))
            continue
        high_hits = [hit for hit in field_hits if hit.confidence_tier == "high"]
        if not high_hits:
            excluded = True
            continue
        low_only = False
        included[field_name] = high_hits[0].value
    if hits and not included:
        excluded = True
    if hits and included and low_only:
        excluded = True
    return SilverUnitRecord(
        unit_id=unit_id,
        document_id=document_id,
        source_text=text,
        assertion_type=assertion_type,
        hits=hits,
        conflicting_rule_ids=sorted(set(conflicting)),
        excluded_from_metrics=excluded and not included,
        included_labels=included,
    )


def label_units(records: Sequence[UnitClassificationRecord]) -> list[SilverUnitRecord]:
    labeled: list[SilverUnitRecord] = []
    for record in records:
        labeled.append(
            build_silver_record(
                unit_id=record.unit_id,
                text=record.source_text,
                assertion_type=record.assertion_type,
                document_id=record.document_key,
            )
        )
    return labeled


def evaluate_silver_agreement(
    artifact_units: Sequence[UnitClassificationRecord],
    *,
    noul_threshold: float = 0.5,
) -> SilverAgreementReport:
    """Compare high-precision silver labels with model outputs.

    Model abstentions and missing coverage are skipped rather than scored as
    negatives.
    """
    silver_records = label_units(artifact_units)
    by_id = {record.unit_id: record for record in artifact_units}
    disagreements: list[SilverDisagreement] = []
    compared = 0
    agreements = 0
    excluded_conflict = 0
    excluded_low = 0
    included_labels = 0

    for silver in silver_records:
        if silver.conflicting_rule_ids:
            excluded_conflict += 1
        low_hits = [hit for hit in silver.hits if hit.confidence_tier == "low"]
        if low_hits and not silver.included_labels:
            excluded_low += 1
        included_labels += len(silver.included_labels)
        model = by_id.get(silver.unit_id)
        if model is None:
            continue
        for field_name, value in silver.included_labels.items():
            model_value: str | bool | None
            probability: float | None
            if field_name == "statement_type":
                model_value, probability = choice_prediction(
                    model, noul_threshold=noul_threshold
                )
            elif field_name in NOUL_QUESTION_IDS:
                model_value, probability = noul_prediction(
                    model, field_name, threshold=noul_threshold
                )
            else:
                continue
            if model_value is None:
                continue
            compared += 1
            if model_value == value:
                agreements += 1
                continue
            rule_ids = sorted(
                {
                    hit.rule_id
                    for hit in silver.hits
                    if hit.field == field_name and hit.confidence_tier == "high"
                }
            )
            disagreements.append(
                SilverDisagreement(
                    unit_id=silver.unit_id,
                    field=field_name,
                    silver_value=value,
                    model_value=model_value,
                    rule_ids=rule_ids,
                    model_probability=probability,
                )
            )

    return SilverAgreementReport(
        unit_count=len(silver_records),
        included_label_count=included_labels,
        excluded_conflict_count=excluded_conflict,
        excluded_low_confidence_count=excluded_low,
        compared=compared,
        agreements=agreements,
        agreement_rate=(agreements / compared) if compared else None,
        disagreements=disagreements,
        records=silver_records,
        notes=[
            "silver labels are never gold",
            "conflicted and low-confidence hits are excluded from agreement",
            "model abstentions are skipped, not scored as negatives",
        ],
    )
