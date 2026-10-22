"""Tests for blind, per-axis agent-reference qualification."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from research_analysis_layer.evals.decision_agent_qualification import (
    AxisQualificationRule,
    QualificationPolicy,
    apply_qualification_report,
    build_qualification_inventory,
    run_blind_qualification,
)
from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    JudgmentRequest,
    ResourceLimits,
)
from research_analysis_layer.evals.decision_agent_references import (
    AgentJudgment,
    AxisJudgment,
    CallUsage,
    ModelIdentity,
    SupportingSpan,
    load_agent_references,
    role_prompt_sha256,
)
from research_analysis_layer.evals.decision_reviews import (
    default_review_dir,
    default_review_records_path,
    sha256_text,
)


NOW = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
TAXONOMY = "qualification taxonomy v1"


def _identity(role: str, *, correlated: bool = False) -> ModelIdentity:
    return ModelIdentity(
        provider="scripted",
        model=f"{role}-model",
        model_family="shared-family" if correlated else f"{role}-family",
        resolved_version=f"{role}-model-2026-10-22",
    )


def _config(*, correlated: bool = False, max_requests: int = 10) -> HarnessConfig:
    return HarnessConfig(
        run_id="qualification-run-1",
        taxonomy_version="taxonomy-v1",
        taxonomy_text=TAXONOMY,
        taxonomy_sha256=sha256_text(TAXONOMY),
        gate_version="qualification-gate-v1",
        role_models={
            role: _identity(role, correlated=correlated)
            for role in ("annotator", "reviewer")
        },
        limits=ResourceLimits(
            max_requests=max_requests,
            max_input_tokens=10_000,
            max_output_tokens=10_000,
            max_elapsed_seconds=30,
            max_estimated_usd=1,
        ),
        adjudicate_disagreements=False,
    )


class BlindQualificationProvider:
    def __init__(self, *, wrong_statement: bool = False, correlated: bool = False) -> None:
        self.wrong_statement = wrong_statement
        self.correlated = correlated
        self.requests: list[JudgmentRequest] = []

    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        target = request.source.target_text
        is_hold = "no compelling reason to reposition" in target
        statement_type = "recommendation" if is_hold else "assertion"
        if self.wrong_statement:
            statement_type = "question"
        values: list[tuple[str, str | bool]] = [
            ("statement_type", statement_type),
            ("is_forecast", not is_hold),
            ("is_causal", not is_hold),
            ("contains_reasoning_bridge", not is_hold),
            ("is_trade_or_action", is_hold),
        ]
        return AgentJudgment(
            judgment_id=f"judgment-{request.source.source_id}-{request.role}",
            source_id=request.source.source_id,
            role=request.role,
            pass_kind="blind_first_pass",
            model=_identity(request.role, correlated=self.correlated),
            role_prompt_sha256=role_prompt_sha256(request.role),
            taxonomy_version=request.taxonomy_version,
            taxonomy_sha256=request.taxonomy_sha256,
            call_id=f"call-{request.source.source_id}-{request.role}",
            created_at=NOW,
            usage=CallUsage(
                input_tokens=20,
                output_tokens=10,
                estimated_usd=0.01,
            ),
            axes=[
                AxisJudgment(
                    axis_id=axis_id,
                    state="labeled",
                    value=value,
                    rationale="Scripted blind classification for qualification testing.",
                    supporting_spans=[
                        SupportingSpan(start=0, end=len(target), text=target)
                    ],
                )
                for axis_id, value in values
            ],
        )


def _rule(
    *,
    human: int = 1,
    scored: int = 1,
    maximum: float = 1.0,
    distinct: int = 1,
    independent: bool = True,
) -> AxisQualificationRule:
    return AxisQualificationRule(
        min_human_support=human,
        min_scored_support=scored,
        min_distinct_values=distinct,
        max_wilson_upper_error=maximum,
        require_independent_model_families=independent,
    )


def _policy(
    rules: dict[str, AxisQualificationRule],
) -> QualificationPolicy:
    return QualificationPolicy(policy_id="qualification-policy-test-v1", axis_rules=rules)


def test_checked_in_human_inventory_has_two_verified_sparse_examples() -> None:
    inventory = build_qualification_inventory(
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
    )
    assert inventory.validation.valid is True
    assert inventory.validation.sources_verified is True
    assert len(inventory.examples) == 2
    assert inventory.excluded == []
    assert all(example.source.split == "qualification" for example in inventory.examples)
    assert all("review-doc" not in example.source.source_id for example in inventory.examples)
    assert {len(example.labels.noul_labels) for example in inventory.examples} == {4}


def test_blind_run_never_sends_human_answers_and_small_set_stays_provisional(
    tmp_path,
) -> None:
    provider = BlindQualificationProvider()
    conservative_rules = {
        axis_id: _rule(human=5, scored=5, maximum=0.20)
        for axis_id in (
            "statement_type",
            "is_forecast",
            "is_causal",
            "contains_reasoning_bridge",
            "is_trade_or_action",
        )
    }
    report = run_blind_qualification(
        output_dir=tmp_path / "qualification",
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
        harness_config=_config(),
        policy=_policy(conservative_rules),
        provider=provider,
    )

    assert len(provider.requests) == 4
    for request in provider.requests:
        payload = request.model_dump(mode="json")
        assert "labels" not in payload
        assert "review_id" not in json.dumps(payload)
        assert request.comparison_judgments == []
    assert report.qualified_axis_ids == []
    assert set(report.provisional_axis_ids) == set(report.results)
    assert report.results["statement_type"].human_support == 2
    assert report.results["statement_type"].correct == 2
    assert report.results["is_market_impact"].human_support == 0
    assert "no frozen qualification rule" in report.results[
        "is_market_impact"
    ].reasons[0]
    summary = (tmp_path / "qualification" / "SUMMARY.md").read_text()
    assert "Explicitly provisional axes" in summary


def test_two_agents_agreeing_on_known_wrong_answer_does_not_qualify(tmp_path) -> None:
    report = run_blind_qualification(
        output_dir=tmp_path / "qualification",
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
        harness_config=_config(),
        policy=_policy(
            {
                "statement_type": _rule(
                    human=2,
                    scored=2,
                    maximum=0.80,
                    distinct=2,
                )
            }
        ),
        provider=BlindQualificationProvider(wrong_statement=True),
    )
    result = report.results["statement_type"]
    assert result.scored_support == 2
    assert result.errors == 2
    assert result.qualified is False
    assert any("Wilson upper error" in reason for reason in result.reasons)


def test_matching_labels_can_pass_only_the_axis_with_a_frozen_rule(tmp_path) -> None:
    output = tmp_path / "qualification"
    report = run_blind_qualification(
        output_dir=output,
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
        harness_config=_config(),
        policy=_policy(
            {
                "statement_type": _rule(
                    human=2,
                    scored=2,
                    maximum=1.0,
                    distinct=2,
                )
            }
        ),
        provider=BlindQualificationProvider(),
    )
    assert report.qualified_axis_ids == ["statement_type"]
    assert report.results["statement_type"].errors == 0
    assert "is_forecast" in report.provisional_axis_ids

    references = load_agent_references(output / "blind_run" / "references.jsonl")
    promoted = apply_qualification_report(references, report)
    assert all(record.lifecycle == "qualified" for record in promoted)
    for record in promoted:
        by_axis = {axis.axis_id: axis for axis in record.accepted_axes}
        assert by_axis["statement_type"].tier == "qualified"
        assert by_axis["statement_type"].qualification_report_id == report.report_id
        assert by_axis["is_forecast"].tier == "provisional"


def test_correlated_model_families_block_qualification(tmp_path) -> None:
    report = run_blind_qualification(
        output_dir=tmp_path / "qualification",
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
        harness_config=_config(correlated=True),
        policy=_policy(
            {
                "statement_type": _rule(
                    human=2,
                    scored=2,
                    maximum=1.0,
                    distinct=2,
                )
            }
        ),
        provider=BlindQualificationProvider(correlated=True),
    )
    result = report.results["statement_type"]
    assert result.qualified is False
    assert result.correlated_acceptances == 2
    assert any("correlated model families" in reason for reason in result.reasons)


def test_unverified_artifact_root_excludes_human_records(tmp_path) -> None:
    inventory = build_qualification_inventory(
        records_path=default_review_records_path(),
        artifact_root=tmp_path,
    )
    assert inventory.examples == []
    assert len(inventory.excluded) == 2
    assert all("artifact_missing" in item.reason_codes for item in inventory.excluded)


def test_incomplete_blind_run_cannot_qualify_even_with_permissive_rule(tmp_path) -> None:
    report = run_blind_qualification(
        output_dir=tmp_path / "qualification",
        records_path=default_review_records_path(),
        artifact_root=default_review_dir() / "sources",
        harness_config=_config(max_requests=1),
        policy=_policy({"statement_type": _rule(maximum=1.0)}),
        provider=BlindQualificationProvider(),
    )
    result = report.results["statement_type"]
    assert result.qualified is False
    assert any("missing 2 source records" in reason for reason in result.reasons)


def test_qualification_output_directory_must_be_new(tmp_path) -> None:
    output = tmp_path / "qualification"
    output.mkdir()
    with pytest.raises(FileExistsError):
        run_blind_qualification(
            output_dir=output,
            records_path=default_review_records_path(),
            artifact_root=default_review_dir() / "sources",
            harness_config=_config(),
            policy=_policy({"statement_type": _rule()}),
            provider=BlindQualificationProvider(),
        )
