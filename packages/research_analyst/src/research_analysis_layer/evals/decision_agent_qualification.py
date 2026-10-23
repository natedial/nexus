"""Blind qualification of agent-reference axes against verified human evidence.

Human answers are held in a provenance inventory and are never included in the
``AgentReferenceSource`` objects sent to the annotation harness. Qualification
is per axis and conservative: missing rules, insufficient support, abstentions,
correlated model families, or a weak error bound keep the axis provisional.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    JudgmentProvider,
    ReferenceBatchHarness,
)
from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AgentReferenceRecord,
    AgentReferenceSource,
    SourceTransformation,
    load_agent_references,
    role_prompt_sha256,
)
from research_analysis_layer.evals.decision_reviews import (
    DecisionReviewRecord,
    ReviewValidationReport,
    ReviewedLabels,
    load_review_records,
    sha256_bytes,
    sha256_text,
    validate_review_records,
)

QUALIFICATION_INVENTORY_SCHEMA = "decision-agent-qualification-inventory-v1"
QUALIFICATION_POLICY_SCHEMA = "decision-agent-qualification-policy-v1"
QUALIFICATION_REPORT_SCHEMA = "decision-agent-qualification-report-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerifiedHumanExample(StrictModel):
    review_id: str = Field(min_length=1)
    source: AgentReferenceSource
    labels: ReviewedLabels
    approval_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_note_reference: str = Field(min_length=1)

    @property
    def expected_axes(self) -> dict[str, str | bool]:
        return {
            "statement_type": self.labels.statement_type,
            **self.labels.noul_labels,
        }


class ExcludedHumanRecord(StrictModel):
    review_id: str
    reason_codes: list[str] = Field(min_length=1)


class QualificationInventory(StrictModel):
    schema_version: Literal[
        "decision-agent-qualification-inventory-v1"
    ] = QUALIFICATION_INVENTORY_SCHEMA
    inventory_id: str = Field(min_length=1)
    records_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation: ReviewValidationReport
    examples: list[VerifiedHumanExample]
    excluded: list[ExcludedHumanRecord] = Field(default_factory=list)

    @field_validator("examples")
    @classmethod
    def _unique_examples(
        cls, value: list[VerifiedHumanExample]
    ) -> list[VerifiedHumanExample]:
        review_ids = [item.review_id for item in value]
        source_ids = [item.source.source_id for item in value]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("qualification examples repeat a review_id")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("qualification examples repeat a source_id")
        return value


class AxisQualificationRule(StrictModel):
    min_human_support: int = Field(ge=1)
    min_scored_support: int = Field(ge=1)
    min_positive: int = Field(default=0, ge=0)
    min_negative: int = Field(default=0, ge=0)
    min_distinct_values: int = Field(default=1, ge=1)
    max_wilson_upper_error: float = Field(ge=0, le=1)
    require_independent_model_families: bool = True

    @model_validator(mode="after")
    def _coherent_support(self) -> AxisQualificationRule:
        if self.min_scored_support > self.min_human_support:
            raise ValueError("min_scored_support cannot exceed min_human_support")
        if self.min_positive + self.min_negative > self.min_human_support:
            raise ValueError("positive/negative minima exceed human support")
        return self


class QualificationPolicy(StrictModel):
    schema_version: Literal[
        "decision-agent-qualification-policy-v1"
    ] = QUALIFICATION_POLICY_SCHEMA
    policy_id: str = Field(min_length=1)
    confidence_level: Literal[0.95] = 0.95
    axis_rules: dict[str, AxisQualificationRule]

    @field_validator("axis_rules")
    @classmethod
    def _known_axes(
        cls, value: dict[str, AxisQualificationRule]
    ) -> dict[str, AxisQualificationRule]:
        unknown = sorted(set(value) - set(AXIS_IDS))
        if unknown:
            raise ValueError(f"qualification policy contains unknown axes: {unknown}")
        return value


class AxisQualificationResult(StrictModel):
    axis_id: str
    human_support: int = Field(ge=0)
    scored_support: int = Field(ge=0)
    correct: int = Field(ge=0)
    errors: int = Field(ge=0)
    abstained_or_missing: int = Field(ge=0)
    positive_support: int = Field(ge=0)
    negative_support: int = Field(ge=0)
    distinct_expected_values: int = Field(ge=0)
    correlated_acceptances: int = Field(ge=0)
    error_rate: float | None = Field(default=None, ge=0, le=1)
    wilson_upper_error: float | None = Field(default=None, ge=0, le=1)
    qualified: bool
    reasons: list[str]


class QualificationReport(StrictModel):
    schema_version: Literal[
        "decision-agent-qualification-report-v1"
    ] = QUALIFICATION_REPORT_SCHEMA
    report_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    inventory_id: str = Field(min_length=1)
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_count: int = Field(ge=0)
    results: dict[str, AxisQualificationResult]
    qualified_axis_ids: list[str]
    provisional_axis_ids: list[str]
    limitations: list[str]


def _opaque_source_id(record: DecisionReviewRecord) -> str:
    seed = (
        f"{record.review_id}:{record.reviewed_text_sha256}:"
        f"{record.question_set_version}"
    )
    return "qualification-source-" + hashlib.sha256(seed.encode()).hexdigest()[:20]


def _source_from_review(record: DecisionReviewRecord) -> AgentReferenceSource:
    source_text = record.model_input
    target_start = source_text.find(record.reviewed_text)
    if target_start < 0:
        raise ValueError(f"reviewed text missing from model input for {record.review_id}")
    transformations = []
    if source_text != record.reviewed_text:
        transformations.append(
            SourceTransformation(
                transformation_id="reviewed-target-scope",
                kind="other",
                description=(
                    "The human-reviewed target is a narrower exact span of the "
                    "stored model input."
                ),
                meaning_preserved=None,
            )
        )
    return AgentReferenceSource(
        source_id=_opaque_source_id(record),
        document_id=record.document_id,
        document_type=record.document_type,
        unit_id=record.unit_id,
        source_lineage_id=f"human-review:{record.document_id}",
        split="qualification",
        source_text=source_text,
        source_text_sha256=sha256_text(source_text),
        target_text=record.reviewed_text,
        target_text_sha256=record.reviewed_text_sha256,
        target_start=target_start,
        target_end=target_start + len(record.reviewed_text),
        stored_model_input=source_text,
        transformations=transformations,
        source_artifact=record.source_artifact,
    )


def build_qualification_inventory(
    *, records_path: Path, artifact_root: Path
) -> QualificationInventory:
    """Inventory only source- and approval-verified agreed human records."""

    records = load_review_records(records_path)
    validation = validate_review_records(records, artifact_root=artifact_root)
    issues_by_review: dict[str, list[str]] = {}
    global_errors: list[str] = []
    for issue in validation.issues:
        if issue.level != "error":
            continue
        if issue.review_id is None:
            global_errors.append(issue.code)
        else:
            issues_by_review.setdefault(issue.review_id, []).append(issue.code)

    examples: list[VerifiedHumanExample] = []
    excluded: list[ExcludedHumanRecord] = []
    for record in records:
        reasons = list(global_errors)
        reasons.extend(issues_by_review.get(record.review_id, []))
        if record.status != "agreed":
            reasons.append(f"status_{record.status}")
        if record.approval_trace is None:
            reasons.append("approval_trace_missing")
        if reasons:
            excluded.append(
                ExcludedHumanRecord(
                    review_id=record.review_id,
                    reason_codes=sorted(set(reasons)),
                )
            )
            continue
        assert record.approval_trace is not None
        examples.append(
            VerifiedHumanExample(
                review_id=record.review_id,
                source=_source_from_review(record),
                labels=record.labels,
                approval_source_sha256=record.approval_trace.source_sha256,
                approval_note_reference=record.approval_trace.note_reference,
            )
        )

    records_hash = sha256_bytes(records_path.read_bytes())
    inventory_seed = {
        "records_file_sha256": records_hash,
        "review_ids": [item.review_id for item in examples],
        "source_hashes": [item.source.target_text_sha256 for item in examples],
    }
    inventory_id = "qualification-inventory-" + sha256_text(
        json.dumps(inventory_seed, sort_keys=True, separators=(",", ":"))
    )[:20]
    return QualificationInventory(
        inventory_id=inventory_id,
        records_file_sha256=records_hash,
        validation=validation,
        examples=examples,
        excluded=excluded,
    )


def qualification_configuration_fingerprint(
    references: Sequence[AgentReferenceRecord],
) -> str:
    """Bind qualification to model, prompt, taxonomy, and gate configuration."""

    first_pass_configurations: set[
        tuple[str, str, str, str, str, str, str, str, str]
    ] = set()
    gate_versions: set[str] = set()
    for reference in references:
        first_pass_configurations.update(
            (
                item.role,
                item.model.provider,
                item.model.model,
                item.model.model_family,
                item.model.resolved_version,
                item.role_prompt_version,
                item.role_prompt_sha256,
                item.taxonomy_version,
                item.taxonomy_sha256,
            )
            for item in reference.judgments
            if item.role in {"annotator", "reviewer"}
        )
        gate_versions.update(item.gate_version for item in reference.accepted_axes)
    configurations_by_role: dict[str, int] = Counter(
        item[0] for item in first_pass_configurations
    )
    if any(count != 1 for count in configurations_by_role.values()):
        raise ValueError("qualification references mix multiple role configurations")
    if len(gate_versions) > 1:
        raise ValueError("qualification references mix multiple gate versions")
    if not first_pass_configurations:
        return sha256_text("no-reference-configuration")
    return _configuration_fingerprint(
        first_pass_configurations=first_pass_configurations,
        gate_versions=gate_versions,
    )


def _configuration_fingerprint(
    *,
    first_pass_configurations: set[
        tuple[str, str, str, str, str, str, str, str, str]
    ],
    gate_versions: set[str],
) -> str:
    payload = {
        "first_passes": sorted(first_pass_configurations),
        "gate_versions": sorted(gate_versions),
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def harness_configuration_fingerprint(config: HarnessConfig) -> str:
    """Predict the qualification fingerprint for a frozen harness config."""

    first_passes = set()
    for role in ("annotator", "reviewer"):
        identity = config.role_models[role]
        first_passes.add(
            (
                role,
                identity.provider,
                identity.model,
                identity.model_family,
                identity.resolved_version,
                "decision-reference-role-v1",
                role_prompt_sha256(role),
                config.taxonomy_version,
                config.taxonomy_sha256,
            )
        )
    return _configuration_fingerprint(
        first_pass_configurations=first_passes,
        gate_versions={config.gate_version},
    )


def _wilson_upper(errors: int, support: int, z: float = 1.959963984540054) -> float | None:
    if support == 0:
        return None
    proportion = errors / support
    denominator = 1 + (z * z / support)
    centre = proportion + (z * z / (2 * support))
    margin = z * math.sqrt(
        (proportion * (1 - proportion) / support)
        + (z * z / (4 * support * support))
    )
    return min(1.0, (centre + margin) / denominator)


def build_qualification_report(
    *,
    inventory: QualificationInventory,
    references: Sequence[AgentReferenceRecord],
    policy: QualificationPolicy,
) -> QualificationReport:
    by_source = {record.source.source_id: record for record in references}
    if len(by_source) != len(references):
        raise ValueError("qualification references repeat a source_id")
    expected_sources = {item.source.source_id for item in inventory.examples}
    unexpected = sorted(set(by_source) - expected_sources)
    if unexpected:
        raise ValueError(f"qualification references include unknown sources: {unexpected}")
    missing_source_count = len(expected_sources - set(by_source))

    results: dict[str, AxisQualificationResult] = {}
    for axis_id in AXIS_IDS:
        expected_values: list[str | bool] = []
        accepted_values: list[tuple[str | bool, bool]] = []
        correct = 0
        errors = 0
        abstained = 0
        for example in inventory.examples:
            expected = example.expected_axes.get(axis_id)
            if expected is None:
                continue
            expected_values.append(expected)
            reference = by_source.get(example.source.source_id)
            accepted = None
            if reference is not None:
                accepted = next(
                    (item for item in reference.accepted_axes if item.axis_id == axis_id),
                    None,
                )
            if accepted is None:
                abstained += 1
                continue
            accepted_values.append((accepted.value, accepted.correlated_models))
            if accepted.value == expected:
                correct += 1
            else:
                errors += 1

        human_support = len(expected_values)
        scored_support = len(accepted_values)
        positives = sum(value is True for value in expected_values)
        negatives = sum(value is False for value in expected_values)
        distinct_values = len(set(expected_values))
        correlated = sum(is_correlated for _, is_correlated in accepted_values)
        error_rate = errors / scored_support if scored_support else None
        upper = _wilson_upper(errors, scored_support)
        reasons: list[str] = []
        if missing_source_count:
            reasons.append(
                f"qualification run is missing {missing_source_count} source records"
            )
        rule = policy.axis_rules.get(axis_id)
        if rule is None:
            reasons.append("no frozen qualification rule for this axis")
        else:
            if human_support < rule.min_human_support:
                reasons.append(
                    f"human support {human_support} < {rule.min_human_support}"
                )
            if scored_support < rule.min_scored_support:
                reasons.append(
                    f"scored support {scored_support} < {rule.min_scored_support}"
                )
            if positives < rule.min_positive:
                reasons.append(f"positive support {positives} < {rule.min_positive}")
            if negatives < rule.min_negative:
                reasons.append(f"negative support {negatives} < {rule.min_negative}")
            if distinct_values < rule.min_distinct_values:
                reasons.append(
                    f"distinct expected values {distinct_values} < "
                    f"{rule.min_distinct_values}"
                )
            if upper is None or upper > rule.max_wilson_upper_error:
                reasons.append(
                    "Wilson upper error is unavailable"
                    if upper is None
                    else (
                        f"Wilson upper error {upper:.4f} > "
                        f"{rule.max_wilson_upper_error:.4f}"
                    )
                )
            if rule.require_independent_model_families and correlated:
                reasons.append(
                    f"{correlated} accepted examples used correlated model families"
                )
        results[axis_id] = AxisQualificationResult(
            axis_id=axis_id,
            human_support=human_support,
            scored_support=scored_support,
            correct=correct,
            errors=errors,
            abstained_or_missing=abstained,
            positive_support=positives,
            negative_support=negatives,
            distinct_expected_values=distinct_values,
            correlated_acceptances=correlated,
            error_rate=error_rate,
            wilson_upper_error=upper,
            qualified=not reasons,
            reasons=reasons,
        )

    qualified = [axis_id for axis_id in AXIS_IDS if results[axis_id].qualified]
    provisional = [axis_id for axis_id in AXIS_IDS if axis_id not in qualified]
    configuration = qualification_configuration_fingerprint(references)
    report_seed = {
        "inventory_id": inventory.inventory_id,
        "policy": policy.model_dump(mode="json"),
        "configuration_fingerprint": configuration,
        "results": {
            axis_id: result.model_dump(mode="json")
            for axis_id, result in results.items()
        },
    }
    report_id = "qualification-report-" + sha256_text(
        json.dumps(report_seed, sort_keys=True, separators=(",", ":"))
    )[:20]
    return QualificationReport(
        report_id=report_id,
        policy_id=policy.policy_id,
        inventory_id=inventory.inventory_id,
        configuration_fingerprint=configuration,
        reference_count=len(references),
        results=results,
        qualified_axis_ids=qualified,
        provisional_axis_ids=provisional,
        limitations=[
            "Qualification measures agreement with verified human labels only on "
            "the explicitly reviewed axes.",
            "The current human set may be too small or narrow to qualify any axis.",
            "Agent agreement and a passing bound do not establish production safety.",
        ],
    )


def apply_qualification_report(
    references: Sequence[AgentReferenceRecord],
    report: QualificationReport,
) -> list[AgentReferenceRecord]:
    """Return new records with only report-qualified axes promoted.

    The model/prompt/taxonomy/gate configuration must match exactly. The input
    records are not mutated, and unqualified axes remain provisional.
    """

    fingerprint = qualification_configuration_fingerprint(references)
    if fingerprint != report.configuration_fingerprint:
        raise ValueError("qualification report does not match reference configuration")
    qualified_ids = set(report.qualified_axis_ids)
    promoted: list[AgentReferenceRecord] = []
    for reference in references:
        payload = reference.model_dump(mode="json")
        promoted_count = 0
        for axis in payload["accepted_axes"]:
            if axis["axis_id"] not in qualified_ids:
                continue
            axis["tier"] = "qualified"
            axis["qualification_report_id"] = report.report_id
            promoted_count += 1
        if promoted_count:
            payload["lifecycle"] = "qualified"
        promoted.append(AgentReferenceRecord.model_validate(payload))
    return promoted


def run_blind_qualification(
    *,
    output_dir: Path,
    records_path: Path,
    artifact_root: Path,
    harness_config: HarnessConfig,
    policy: QualificationPolicy,
    provider: JudgmentProvider,
) -> QualificationReport:
    """Run the harness on answer-free sources, then score after calls finish."""

    output_dir.mkdir(parents=True, exist_ok=False)
    inventory = build_qualification_inventory(
        records_path=records_path, artifact_root=artifact_root
    )
    harness_dir = output_dir / "blind_run"
    ReferenceBatchHarness(provider).run(
        output_dir=harness_dir,
        sources=[item.source for item in inventory.examples],
        config=harness_config,
    )
    references = load_agent_references(harness_dir / "references.jsonl")
    report = build_qualification_report(
        inventory=inventory,
        references=references,
        policy=policy,
    )
    (output_dir / "provenance_inventory.json").write_text(
        json.dumps(inventory.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "qualification.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = [
        "# Blind agent-reference qualification",
        "",
        f"- Verified human examples: {len(inventory.examples)}",
        f"- Excluded human records: {len(inventory.excluded)}",
        f"- Qualified axes: {len(report.qualified_axis_ids)}",
        f"- Provisional axes: {len(report.provisional_axis_ids)}",
        "",
        "Human answers were not included in annotation requests. Qualification was "
        "computed only after the blind run completed.",
        "",
        "## Qualified axes",
        "",
        *(f"- `{axis_id}`" for axis_id in report.qualified_axis_ids),
        "",
        "## Explicitly provisional axes",
        "",
        *(
            f"- `{axis_id}`: {'; '.join(report.results[axis_id].reasons)}"
            for axis_id in report.provisional_axis_ids
        ),
        "",
    ]
    (output_dir / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")
    return report


__all__ = [
    "AxisQualificationResult",
    "AxisQualificationRule",
    "ExcludedHumanRecord",
    "QualificationInventory",
    "QualificationPolicy",
    "QualificationReport",
    "VerifiedHumanExample",
    "build_qualification_inventory",
    "build_qualification_report",
    "apply_qualification_report",
    "harness_configuration_fingerprint",
    "qualification_configuration_fingerprint",
    "run_blind_qualification",
]
