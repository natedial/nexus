"""Tests for deterministic, no-spend agent-reference pilot preparation."""

from __future__ import annotations

import json

import pytest

from research_analysis_layer.evals.decision_agent_pilot import (
    build_pilot_specification,
    dry_run_pilot,
    load_pilot_candidates,
    reviewed_unit_keys,
    select_stratified_pilot,
    write_pilot_preparation,
)
from research_analysis_layer.evals.decision_agent_provider import TokenPricing
from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    ResourceLimits,
)
from research_analysis_layer.evals.decision_agent_references import ModelIdentity
from research_analysis_layer.evals.decision_reviews import (
    default_review_dir,
    default_review_records_path,
    load_review_records,
    sha256_text,
)


TAXONOMY = "pilot decision taxonomy v1"


def _identity(role: str) -> ModelIdentity:
    model = f"high-capability-{role}-2026-10-23"
    return ModelIdentity(
        provider="configured-live-provider",
        model=model,
        model_family=f"independent-{role}-family",
        resolved_version=model,
    )


def _harness_config(
    *, max_requests: int = 100, max_input_tokens: int = 1_000_000
) -> HarnessConfig:
    return HarnessConfig(
        run_id="agent-reference-pilot-1",
        execution_mode="live",
        taxonomy_version="pilot-taxonomy-v1",
        taxonomy_text=TAXONOMY,
        taxonomy_sha256=sha256_text(TAXONOMY),
        gate_version="pilot-gate-v1",
        role_models={
            role: _identity(role)
            for role in ("annotator", "reviewer", "adjudicator")
        },
        limits=ResourceLimits(
            max_requests=max_requests,
            max_input_tokens=max_input_tokens,
            max_output_tokens=1_000_000,
            max_elapsed_seconds=3600,
            max_estimated_usd=10,
        ),
    )


def _pricing() -> dict[str, TokenPricing]:
    return {
        role: TokenPricing(
            input_usd_per_million=2,
            output_usd_per_million=10,
            source="frozen test price card 2026-10-23",
        )
        for role in ("annotator", "reviewer", "adjudicator")
    }


def _selection(max_units: int = 12):
    artifact_root = default_review_dir() / "sources"
    artifacts = sorted(artifact_root.glob("shadow_*.json"))
    reviews = load_review_records(default_review_records_path())
    candidates, excluded = load_pilot_candidates(
        artifact_root=artifact_root,
        artifact_paths=artifacts,
        excluded_unit_keys=reviewed_unit_keys(reviews),
        document_types={"doc_002": "rates", "doc_003": "fx"},
    )
    return select_stratified_pilot(
        candidates=candidates,
        max_units=max_units,
        seed="pilot-seed-v1",
        excluded_reviewed_count=excluded,
    )


def _spec(selection, *, config: HarnessConfig | None = None):
    return build_pilot_specification(
        pilot_id="agent-reference-pilot-1",
        selection=selection,
        harness_config=config or _harness_config(),
        pricing_by_role=_pricing(),
    )


def test_checked_in_artifacts_yield_24_candidates_after_gold_exclusion() -> None:
    selection = _selection()
    assert selection.candidate_count == 24
    assert selection.excluded_reviewed_count == 2
    assert len(selection.selected) == 12
    assert set(selection.document_counts) == {"doc_002", "doc_003"}
    reviewed = reviewed_unit_keys(load_review_records(default_review_records_path()))
    assert all(
        (item.source.document_id, item.source.unit_id) not in reviewed
        for item in selection.selected
    )
    assert all(item.source.split == "development" for item in selection.selected)
    assert all(item.source.source_artifact.path.startswith("shadow_") for item in selection.selected)


def test_selection_is_deterministic_and_covers_multiple_strata() -> None:
    first = _selection()
    second = _selection()
    assert first.selection_id == second.selection_id
    assert [item.source.source_id for item in first.selected] == [
        item.source.source_id for item in second.selected
    ]
    assert len(first.assertion_type_counts) >= 3
    assert any(tag.startswith("failure_mode:") for tag in first.tag_counts)


def test_no_spend_dry_run_validates_call_token_and_dollar_envelopes(tmp_path) -> None:
    selection = _selection()
    specification = _spec(selection)
    output = tmp_path / "pilot-preparation"
    report = write_pilot_preparation(
        output_dir=output,
        selection=selection,
        specification=specification,
    )
    assert report.ready_for_live_execution is True
    assert report.no_network_calls_performed is True
    assert report.minimum_annotation_calls == 24
    assert report.maximum_annotation_calls_before_retries == 36
    assert report.planned_audit_calls == 2
    assert report.estimated_minimum_usd > 0
    assert report.estimated_maximum_usd_before_retries > report.estimated_minimum_usd
    assert (output / "sources.jsonl").is_file()
    assert (output / "pilot_spec.json").is_file()
    assert "No network" in (output / "SUMMARY.md").read_text()
    source_rows = [
        json.loads(line)
        for line in (output / "sources.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(source_rows) == 12


def test_dry_run_fails_closed_when_request_cap_cannot_cover_blind_passes() -> None:
    selection = _selection()
    report = dry_run_pilot(
        selection=selection,
        specification=_spec(selection, config=_harness_config(max_requests=10)),
    )
    assert report.ready_for_live_execution is False
    assert any("annotation envelope" in error for error in report.errors)


def test_dry_run_detects_source_inventory_drift() -> None:
    selection = _selection()
    specification = _spec(selection)
    payload = specification.model_dump(mode="json")
    payload["source_inventory_sha256"] = "0" * 64
    drifted = type(specification).model_validate(payload)
    report = dry_run_pilot(selection=selection, specification=drifted)
    assert report.ready_for_live_execution is False
    assert any("inventory hash" in error for error in report.errors)


def test_dry_run_rejects_qualification_from_a_different_configuration() -> None:
    selection = _selection()
    specification = build_pilot_specification(
        pilot_id="agent-reference-pilot-1",
        selection=selection,
        harness_config=_harness_config(),
        pricing_by_role=_pricing(),
        qualification_report_id="qualification-report-1",
        qualification_configuration_fingerprint="0" * 64,
        qualified_axis_ids=["statement_type"],
    )
    report = dry_run_pilot(selection=selection, specification=specification)
    assert report.ready_for_live_execution is False
    assert any("fingerprint" in error for error in report.errors)


def test_pilot_cap_and_preparation_directory_are_immutable(tmp_path) -> None:
    with pytest.raises(ValueError, match="between 1 and 50"):
        select_stratified_pilot(candidates=[], max_units=51, seed="seed")

    selection = _selection()
    output = tmp_path / "pilot-preparation"
    output.mkdir()
    with pytest.raises(FileExistsError):
        write_pilot_preparation(
            output_dir=output,
            selection=selection,
            specification=_spec(selection),
        )
