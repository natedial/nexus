"""No-spend preparation for a bounded agent-reference pilot."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_analysis_layer.evals.decision_agent_provider import TokenPricing
from research_analysis_layer.evals.decision_agent_qualification import (
    harness_configuration_fingerprint,
)
from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    Role,
)
from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AgentReferenceSource,
)
from research_analysis_layer.evals.decision_artifacts import load_shadow_artifact
from research_analysis_layer.evals.decision_reviews import (
    DecisionReviewRecord,
    SourceArtifactReference,
    sha256_bytes,
    sha256_text,
)


PILOT_SELECTION_SCHEMA = "decision-agent-pilot-selection-v1"
PILOT_SPEC_SCHEMA = "decision-agent-pilot-spec-v1"
PILOT_DRY_RUN_SCHEMA = "decision-agent-pilot-dry-run-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PilotCandidate(StrictModel):
    source: AgentReferenceSource
    assertion_type: str | None = None
    selection_tags: list[str]

    @field_validator("selection_tags")
    @classmethod
    def _unique_tags(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("pilot candidate tags must be unique")
        return sorted(value)


class PilotSelection(StrictModel):
    schema_version: Literal[
        "decision-agent-pilot-selection-v1"
    ] = PILOT_SELECTION_SCHEMA
    selection_id: str = Field(min_length=1)
    seed: str = Field(min_length=1)
    max_units: int = Field(gt=0, le=50)
    candidate_count: int = Field(ge=0)
    excluded_reviewed_count: int = Field(ge=0)
    selected: list[PilotCandidate]
    document_counts: dict[str, int]
    assertion_type_counts: dict[str, int]
    tag_counts: dict[str, int]

    @model_validator(mode="after")
    def _consistent_counts(self) -> PilotSelection:
        if len(self.selected) > self.max_units:
            raise ValueError("pilot selection exceeds max_units")
        if sum(self.document_counts.values()) != len(self.selected):
            raise ValueError("document counts do not match selected sources")
        return self


class PilotSpecification(StrictModel):
    schema_version: Literal["decision-agent-pilot-spec-v1"] = PILOT_SPEC_SCHEMA
    pilot_id: str = Field(min_length=1)
    selection_id: str = Field(min_length=1)
    source_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    harness_config: HarnessConfig
    pricing_by_role: dict[Role, TokenPricing]
    audit_rate: float = Field(default=0.10, gt=0, le=0.50)
    qualification_report_id: str | None = None
    qualification_configuration_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    qualified_axis_ids: list[str] = Field(default_factory=list)

    @field_validator("qualified_axis_ids")
    @classmethod
    def _known_qualified_axes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("qualified_axis_ids cannot contain duplicates")
        unknown = sorted(set(value) - set(AXIS_IDS))
        if unknown:
            raise ValueError(f"qualified_axis_ids contains unknown axes: {unknown}")
        return value

    @model_validator(mode="after")
    def _live_caps_and_prices(self) -> PilotSpecification:
        if self.harness_config.execution_mode != "live":
            raise ValueError("pilot specification must freeze a live harness config")
        if self.harness_config.run_id != self.pilot_id:
            raise ValueError("pilot_id must match the frozen harness run_id")
        missing_prices = set(self.harness_config.role_models) - set(self.pricing_by_role)
        if missing_prices:
            raise ValueError(f"pilot pricing missing roles: {sorted(missing_prices)}")
        if self.qualified_axis_ids and (
            not self.qualification_report_id
            or not self.qualification_configuration_fingerprint
        ):
            raise ValueError(
                "qualified axes require a report ID and configuration fingerprint"
            )
        return self


class PilotDryRunReport(StrictModel):
    schema_version: Literal[
        "decision-agent-pilot-dry-run-v1"
    ] = PILOT_DRY_RUN_SCHEMA
    pilot_id: str
    ready_for_live_execution: bool
    selected_units: int = Field(ge=0)
    selected_documents: int = Field(ge=0)
    minimum_annotation_calls: int = Field(ge=0)
    maximum_annotation_calls_before_retries: int = Field(ge=0)
    planned_audit_calls: int = Field(ge=0)
    estimated_initial_input_tokens: int = Field(ge=0)
    estimated_initial_output_tokens: int = Field(ge=0)
    estimated_minimum_usd: float = Field(ge=0)
    estimated_maximum_usd_before_retries: float = Field(ge=0)
    errors: list[str]
    warnings: list[str]
    no_network_calls_performed: Literal[True] = True


def reviewed_unit_keys(
    records: Sequence[DecisionReviewRecord],
) -> set[tuple[str, str]]:
    """Keep qualification/human-reviewed units out of the expansion pilot."""

    return {
        (record.document_id, record.unit_id)
        for record in records
        if record.status == "agreed"
    }


def _relative_artifact_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"pilot artifact is outside artifact_root: {path}") from exc


def load_pilot_candidates(
    *,
    artifact_root: Path,
    artifact_paths: Sequence[Path],
    excluded_unit_keys: set[tuple[str, str]] | None = None,
    document_types: Mapping[str, str] | None = None,
) -> tuple[list[PilotCandidate], int]:
    """Build exact-scope candidates from explicitly approved shadow artifacts."""

    excluded = excluded_unit_keys or set()
    document_types = document_types or {}
    candidates: list[PilotCandidate] = []
    excluded_count = 0
    seen_keys: set[tuple[str, str]] = set()
    for artifact_path in sorted(path.resolve() for path in artifact_paths):
        relative_path = _relative_artifact_path(artifact_root, artifact_path)
        artifact_bytes = artifact_path.read_bytes()
        artifact_hash = sha256_bytes(artifact_bytes)
        artifact = load_shadow_artifact(artifact_path)
        if not artifact.document_key:
            raise ValueError(f"pilot artifact lacks document_key: {artifact_path}")
        for unit in artifact.units:
            key = (artifact.document_key, unit.unit_id)
            if key in seen_keys:
                raise ValueError(f"duplicate pilot unit across artifacts: {key}")
            seen_keys.add(key)
            if key in excluded:
                excluded_count += 1
                continue
            text = unit.source_text
            if not text.strip():
                continue
            provenance = unit.provenance or {}
            tags = [
                f"coverage:{unit.coverage_status}",
                f"assertion_type:{unit.assertion_type or 'unknown'}",
            ]
            if unit.error or unit.coverage_status in {"partial", "failed", "missing"}:
                tags.append("failure_mode:incomplete_classification")
            if any(result.status == "uncertain" for result in unit.results):
                tags.append("failure_mode:uncertain_output")
            section_title = str(provenance.get("doc_section_title") or "").strip()
            if section_title and text.startswith(section_title) and ":" in text:
                tags.append("failure_mode:context_prefix")
            source_seed = f"{artifact_hash}:{artifact.document_key}:{unit.unit_id}"
            source_id = "pilot-source-" + hashlib.sha256(
                source_seed.encode()
            ).hexdigest()[:20]
            source = AgentReferenceSource(
                source_id=source_id,
                document_id=artifact.document_key,
                document_type=document_types.get(artifact.document_key),
                unit_id=unit.unit_id,
                source_lineage_id=f"shadow-document:{artifact.document_key}",
                split="development",
                source_text=text,
                source_text_sha256=sha256_text(text),
                target_text=text,
                target_text_sha256=sha256_text(text),
                target_start=0,
                target_end=len(text),
                surrounding_context=section_title or None,
                stored_model_input=text,
                source_artifact=SourceArtifactReference(
                    path=relative_path,
                    sha256=artifact_hash,
                ),
            )
            candidates.append(
                PilotCandidate(
                    source=source,
                    assertion_type=unit.assertion_type,
                    selection_tags=tags,
                )
            )
    return candidates, excluded_count


def _seeded_rank(seed: str, source_id: str) -> str:
    return hashlib.sha256(f"{seed}:{source_id}".encode()).hexdigest()


def select_stratified_pilot(
    *,
    candidates: Sequence[PilotCandidate],
    max_units: int,
    seed: str,
    excluded_reviewed_count: int = 0,
) -> PilotSelection:
    """Greedily cover documents, assertion types, and failure-mode tags."""

    if max_units <= 0 or max_units > 50:
        raise ValueError("max_units must be between 1 and 50")
    by_source = {item.source.source_id: item for item in candidates}
    if len(by_source) != len(candidates):
        raise ValueError("pilot candidates repeat a source_id")
    remaining = list(candidates)
    selected: list[PilotCandidate] = []
    seen_documents: set[str] = set()
    seen_types: set[str] = set()
    seen_tags: set[str] = set()
    while remaining and len(selected) < max_units:
        def score(item: PilotCandidate) -> tuple[int, int, int, int]:
            assertion_type = item.assertion_type or "unknown"
            new_tags = sum(tag not in seen_tags for tag in item.selection_tags)
            return (
                int(item.source.document_id not in seen_documents),
                int(assertion_type not in seen_types),
                new_tags,
                -int(_seeded_rank(seed, item.source.source_id), 16),
            )

        chosen = max(remaining, key=score)
        remaining.remove(chosen)
        selected.append(chosen)
        seen_documents.add(chosen.source.document_id)
        seen_types.add(chosen.assertion_type or "unknown")
        seen_tags.update(chosen.selection_tags)

    document_counts = Counter(item.source.document_id for item in selected)
    type_counts = Counter(item.assertion_type or "unknown" for item in selected)
    tag_counts = Counter(tag for item in selected for tag in item.selection_tags)
    selection_seed = {
        "seed": seed,
        "max_units": max_units,
        "selected_source_ids": [item.source.source_id for item in selected],
    }
    selection_id = "pilot-selection-" + sha256_text(
        json.dumps(selection_seed, sort_keys=True, separators=(",", ":"))
    )[:20]
    return PilotSelection(
        selection_id=selection_id,
        seed=seed,
        max_units=max_units,
        candidate_count=len(candidates),
        excluded_reviewed_count=excluded_reviewed_count,
        selected=selected,
        document_counts=dict(sorted(document_counts.items())),
        assertion_type_counts=dict(sorted(type_counts.items())),
        tag_counts=dict(sorted(tag_counts.items())),
    )


def source_inventory_sha256(selection: PilotSelection) -> str:
    payload = [item.source.model_dump(mode="json") for item in selection.selected]
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def build_pilot_specification(
    *,
    pilot_id: str,
    selection: PilotSelection,
    harness_config: HarnessConfig,
    pricing_by_role: Mapping[Role, TokenPricing],
    audit_rate: float = 0.10,
    qualification_report_id: str | None = None,
    qualification_configuration_fingerprint: str | None = None,
    qualified_axis_ids: Sequence[str] = (),
) -> PilotSpecification:
    return PilotSpecification(
        pilot_id=pilot_id,
        selection_id=selection.selection_id,
        source_inventory_sha256=source_inventory_sha256(selection),
        harness_config=harness_config,
        pricing_by_role=dict(pricing_by_role),
        audit_rate=audit_rate,
        qualification_report_id=qualification_report_id,
        qualification_configuration_fingerprint=(
            qualification_configuration_fingerprint
        ),
        qualified_axis_ids=list(qualified_axis_ids),
    )


def _estimated_input_tokens(source: AgentReferenceSource, taxonomy: str) -> int:
    # Deliberately conservative character-based estimate for the no-spend check.
    characters = len(source.target_text) + len(source.surrounding_context or "")
    characters += len(taxonomy) + 10_000  # role instructions + JSON schema overhead
    return math.ceil(characters / 4)


def dry_run_pilot(
    *, selection: PilotSelection, specification: PilotSpecification
) -> PilotDryRunReport:
    errors: list[str] = []
    warnings: list[str] = []
    if specification.selection_id != selection.selection_id:
        errors.append("pilot specification selection_id does not match selection")
    if specification.source_inventory_sha256 != source_inventory_sha256(selection):
        errors.append("pilot source inventory hash does not match specification")
    if specification.qualified_axis_ids:
        expected_fingerprint = harness_configuration_fingerprint(
            specification.harness_config
        )
        if (
            specification.qualification_configuration_fingerprint
            != expected_fingerprint
        ):
            errors.append(
                "qualification report fingerprint does not match pilot configuration"
            )
    unit_count = len(selection.selected)
    if unit_count == 0:
        errors.append("pilot selection is empty")
    if unit_count > 50:
        errors.append("pilot exceeds the 50-unit cap")

    minimum_calls = unit_count * 2
    maximum_calls = unit_count * (
        3 if specification.harness_config.adjudicate_disagreements else 2
    )
    audit_calls = math.ceil(unit_count * specification.audit_rate) if unit_count else 0
    config = specification.harness_config
    if config.limits.max_requests < maximum_calls:
        errors.append(
            f"request cap {config.limits.max_requests} is below the "
            f"{maximum_calls}-call annotation envelope before retries"
        )

    input_per_source = [
        _estimated_input_tokens(item.source, config.taxonomy_text)
        for item in selection.selected
    ]
    initial_input = sum(input_per_source) * 2
    # Output is bounded by the configured response schema; this estimate is
    # frozen for budget review and intentionally not presented as actual usage.
    output_per_call = 1_200
    initial_output = minimum_calls * output_per_call
    maximum_input = initial_input
    maximum_output = initial_output
    if config.adjudicate_disagreements:
        maximum_input += sum(
            source_input + (2 * output_per_call) for source_input in input_per_source
        )
        maximum_output += unit_count * output_per_call
    if config.limits.max_input_tokens < maximum_input:
        errors.append(
            f"input-token cap {config.limits.max_input_tokens} is below the "
            f"estimated annotation envelope {maximum_input}"
        )
    if config.limits.max_output_tokens < maximum_output:
        errors.append(
            f"output-token cap {config.limits.max_output_tokens} is below the "
            f"estimated annotation envelope {maximum_output}"
        )

    def role_cost(role: Role, calls: int, input_tokens: int) -> float:
        pricing = specification.pricing_by_role[role]
        return (
            input_tokens * pricing.input_usd_per_million
            + (calls * output_per_call * pricing.output_usd_per_million)
        ) / 1_000_000

    total_source_input = sum(input_per_source)
    minimum_usd = role_cost("annotator", unit_count, total_source_input)
    minimum_usd += role_cost("reviewer", unit_count, total_source_input)
    maximum_annotation_usd = minimum_usd
    if config.adjudicate_disagreements:
        adjudicator_input = total_source_input + (
            unit_count * 2 * output_per_call
        )
        maximum_annotation_usd += role_cost(
            "adjudicator", unit_count, adjudicator_input
        )
    maximum_usd = maximum_annotation_usd
    if audit_calls:
        average_input = math.ceil(total_source_input / max(unit_count, 1))
        maximum_usd += role_cost("reviewer", audit_calls, average_input * audit_calls)
    dollar_cap = config.limits.max_estimated_usd
    if dollar_cap is None:
        errors.append("live pilot is missing a dollar cap")
    elif dollar_cap < maximum_annotation_usd:
        errors.append(
            f"dollar cap {dollar_cap:.4f} is below estimated annotation "
            f"envelope {maximum_annotation_usd:.4f}"
        )

    families = {
        config.role_models[role].model_family for role in ("annotator", "reviewer")
    }
    if len(families) == 1:
        warnings.append(
            "annotator and reviewer share a model family; accepted evidence will be correlated"
        )
    if unit_count < selection.candidate_count:
        warnings.append(
            f"selected {unit_count} of {selection.candidate_count} eligible candidates"
        )
    if not specification.qualified_axis_ids:
        warnings.append(
            "no axes are qualified; pilot outputs remain provisional agent references"
        )

    return PilotDryRunReport(
        pilot_id=specification.pilot_id,
        ready_for_live_execution=not errors,
        selected_units=unit_count,
        selected_documents=len(selection.document_counts),
        minimum_annotation_calls=minimum_calls,
        maximum_annotation_calls_before_retries=maximum_calls,
        planned_audit_calls=audit_calls,
        estimated_initial_input_tokens=initial_input,
        estimated_initial_output_tokens=initial_output,
        estimated_minimum_usd=minimum_usd,
        estimated_maximum_usd_before_retries=maximum_usd,
        errors=errors,
        warnings=warnings,
    )


def write_pilot_preparation(
    *,
    output_dir: Path,
    selection: PilotSelection,
    specification: PilotSpecification,
) -> PilotDryRunReport:
    """Write an immutable preparation bundle without invoking a model client."""

    output_dir.mkdir(parents=True, exist_ok=False)
    report = dry_run_pilot(selection=selection, specification=specification)
    (output_dir / "sources.jsonl").write_text(
        "".join(
            json.dumps(item.source.model_dump(mode="json"), sort_keys=True) + "\n"
            for item in selection.selected
        ),
        encoding="utf-8",
    )
    for name, payload in (
        ("selection.json", selection.model_dump(mode="json")),
        ("pilot_spec.json", specification.model_dump(mode="json")),
        ("dry_run.json", report.model_dump(mode="json")),
    ):
        (output_dir / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    summary = [
        "# Agent-reference pilot preparation",
        "",
        f"- Ready for live execution: **{report.ready_for_live_execution}**",
        f"- Selected units: {report.selected_units}",
        f"- Documents: {report.selected_documents}",
        f"- Blind first-pass calls: {report.minimum_annotation_calls}",
        f"- Maximum annotation calls before retries: "
        f"{report.maximum_annotation_calls_before_retries}",
        f"- Planned audit calls: {report.planned_audit_calls}",
        f"- Estimated minimum USD: {report.estimated_minimum_usd:.4f}",
        f"- Estimated maximum USD before retries: "
        f"{report.estimated_maximum_usd_before_retries:.4f}",
        "",
        "No network or model calls were performed by this preparation command.",
        "",
        "## Errors",
        "",
        *(f"- {item}" for item in report.errors),
        "",
        "## Warnings",
        "",
        *(f"- {item}" for item in report.warnings),
        "",
    ]
    (output_dir / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")
    return report


__all__ = [
    "PilotCandidate",
    "PilotDryRunReport",
    "PilotSelection",
    "PilotSpecification",
    "build_pilot_specification",
    "dry_run_pilot",
    "load_pilot_candidates",
    "reviewed_unit_keys",
    "select_stratified_pilot",
    "source_inventory_sha256",
    "write_pilot_preparation",
]
