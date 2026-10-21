"""Contract tests for agent-reviewed decision references."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from research_analysis_layer.evals.decision_agent_references import (
    AcceptedAxis,
    AgentJudgment,
    AgentReferenceRecord,
    AgentReferenceSource,
    AxisJudgment,
    EscalationExample,
    ModelIdentity,
    PolicyEscalation,
    SupportingSpan,
    escalation_packet,
    load_agent_references,
    load_policy_escalations,
    reference_label_views,
    role_prompt_path,
    role_prompt_sha256,
)
from research_analysis_layer.evals.decision_reviews import (
    DecisionReviewRecord,
    SourceArtifactReference,
    sha256_text,
)


NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _source() -> AgentReferenceSource:
    source_text = "Context. We expect two cuts because growth is slowing. End."
    target = "We expect two cuts because growth is slowing."
    start = source_text.index(target)
    return AgentReferenceSource(
        source_id="source-1",
        document_id="doc-1",
        document_type="rates",
        unit_id="chunk-1:assertion-1",
        source_lineage_id="lineage-doc-1",
        split="development",
        source_text=source_text,
        source_text_sha256=sha256_text(source_text),
        target_text=target,
        target_text_sha256=sha256_text(target),
        target_start=start,
        target_end=start + len(target),
        surrounding_context="Context. … End.",
        source_artifact=SourceArtifactReference(
            path="artifacts/shadow_doc_1.json",
            sha256="a" * 64,
        ),
    )


def _identity(*, family: str, model: str) -> ModelIdentity:
    return ModelIdentity(
        provider="example",
        model=model,
        model_family=family,
        resolved_version=f"{model}-2026-10-01",
    )


def _judgment(
    role: str,
    *,
    judgment_id: str,
    call_id: str,
    family: str,
    model: str,
    statement_type: str = "assertion",
) -> AgentJudgment:
    target = _source().target_text
    forecast = "expect two cuts"
    forecast_start = target.index(forecast)
    return AgentJudgment(
        judgment_id=judgment_id,
        source_id="source-1",
        role=role,
        pass_kind="blind_first_pass",
        model=_identity(family=family, model=model),
        role_prompt_sha256="b" * 64,
        taxonomy_version="decision-question-set-v2",
        taxonomy_sha256="c" * 64,
        call_id=call_id,
        created_at=NOW,
        axes=[
            AxisJudgment(
                axis_id="statement_type",
                state="labeled",
                value=statement_type,
                rationale="The author presents a proposition.",
            ),
            AxisJudgment(
                axis_id="is_forecast",
                state="labeled",
                value=True,
                rationale="It describes an expected future event.",
                supporting_spans=[
                    SupportingSpan(
                        start=forecast_start,
                        end=forecast_start + len(forecast),
                        text=forecast,
                    )
                ],
            ),
        ],
    )


def _reference(*, correlated: bool = False) -> AgentReferenceRecord:
    annotator = _judgment(
        "annotator",
        judgment_id="judgment-a",
        call_id="call-a",
        family="family-a",
        model="model-a",
    )
    reviewer = _judgment(
        "reviewer",
        judgment_id="judgment-r",
        call_id="call-r",
        family="family-a" if correlated else "family-b",
        model="model-r",
    )
    return AgentReferenceRecord(
        reference_id="reference-1",
        source=_source(),
        judgments=[annotator, reviewer],
        accepted_axes=[
            AcceptedAxis(
                axis_id="statement_type",
                value="assertion",
                tier="provisional",
                supporting_judgment_ids=["judgment-a", "judgment-r"],
                gate_version="agent-reference-gate-v1",
                admission_reason="Independent blind agreement.",
                correlated_models=correlated,
            ),
            AcceptedAxis(
                axis_id="is_forecast",
                value=True,
                tier="provisional",
                supporting_judgment_ids=["judgment-a", "judgment-r"],
                gate_version="agent-reference-gate-v1",
                admission_reason="Independent blind agreement.",
                correlated_models=correlated,
            ),
        ],
        quarantined_axes={"is_causal": "Taxonomy boundary is unresolved."},
        lifecycle="provisional",
        release_id="agent-reference-pilot-v1",
    )


def _escalation(
    *,
    escalation_id: str,
    policy_key: str,
    impact_count: int,
    fingerprint: str,
    notified: str | None = None,
) -> PolicyEscalation:
    return PolicyEscalation(
        escalation_id=escalation_id,
        policy_key=policy_key,
        status="pending",
        question="Does this recurring pattern count as market impact?",
        affected_axes=["is_market_impact"],
        case_ids=[f"{policy_key}-case-1"],
        impact_count=impact_count,
        examples=[
            EscalationExample(
                case_id=f"{policy_key}-case-1",
                source_id="source-1",
                excerpt="Yields should fall to 4 percent.",
            )
        ],
        interpretations=[
            "Any market-variable forecast counts.",
            "Only explicit cause-to-market-effect claims count.",
        ],
        recommendation="Use the causal interpretation.",
        recommendation_evidence="It matches the narrower question-set intent.",
        proceed_while_pending="Omit this axis and evaluate unrelated axes.",
        first_seen_at=NOW,
        evidence_fingerprint=fingerprint,
        last_notified_fingerprint=notified,
    )


def test_sparse_reference_preserves_unknown_axes() -> None:
    record = _reference()
    assert record.lifecycle == "provisional"
    assert record.quarantined_axes == {
        "is_causal": "Taxonomy boundary is unresolved."
    }
    assert "is_observation" in record.omitted_axis_ids
    assert "is_observation" not in {
        axis.axis_id for axis in record.accepted_axes
    }

    [view] = reference_label_views([record])
    assert view.statement_type == "assertion"
    assert view.noul_labels == {"is_forecast": True}
    assert view.tiers == {
        "statement_type": "provisional",
        "is_forecast": "provisional",
    }


def test_agent_reference_cannot_claim_human_approval() -> None:
    payload = _reference().model_dump(mode="json")
    payload["approval_trace"] = {
        "source_path": "notes.md",
        "source_sha256": "d" * 64,
        "note_reference": "agreed",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentReferenceRecord.model_validate(payload)


def test_existing_human_schema_does_not_accept_agent_lifecycle() -> None:
    payload = {
        "review_id": "review-1",
        "document_id": "doc-1",
        "unit_id": "unit-1",
        "reviewed_text": "Forecast.",
        "reviewed_text_sha256": sha256_text("Forecast."),
        "stored_model_input_sha256": sha256_text("Forecast."),
        "question_set_version": "decision-question-set-v2",
        "question_set_content_hash": "hash",
        "provider": "jev",
        "model_version": "jev-1",
        "adapter_version": "adapter-1",
        "labels": {"statement_type": "assertion", "noul_labels": {}},
        "reviewer": "agent:model-a",
        "review_date": "2026-10-21",
        "status": "agent_reviewed",
        "rationale": "Model agreement.",
        "source_artifact": {
            "path": "artifact.json",
            "sha256": "e" * 64,
        },
    }
    with pytest.raises(ValidationError, match="status"):
        DecisionReviewRecord.model_validate(payload)


def test_supporting_span_must_match_frozen_target() -> None:
    annotator = _judgment(
        "annotator",
        judgment_id="judgment-a",
        call_id="call-a",
        family="family-a",
        model="model-a",
    )
    annotator.axes[1].supporting_spans[0].text = "wrong span"
    reviewer = _judgment(
        "reviewer",
        judgment_id="judgment-r",
        call_id="call-r",
        family="family-b",
        model="model-r",
    )
    with pytest.raises(ValidationError, match="supporting span text mismatch"):
        AgentReferenceRecord(
            reference_id="bad-spans",
            source=_source(),
            judgments=[annotator, reviewer],
            accepted_axes=[],
            quarantined_axes={"is_forecast": "Bad provenance."},
            lifecycle="quarantined",
        )


def test_accepted_axis_requires_independent_annotator_and_reviewer_calls() -> None:
    payload = _reference().model_dump(mode="json")
    payload["judgments"][1]["call_id"] = "call-a"
    with pytest.raises(ValidationError, match="reuse a call_id"):
        AgentReferenceRecord.model_validate(payload)

    payload = _reference().model_dump(mode="json")
    payload["judgments"][1]["role"] = "annotator"
    with pytest.raises(ValidationError, match="both annotator and reviewer"):
        AgentReferenceRecord.model_validate(payload)


def test_model_family_correlation_is_explicit() -> None:
    assert _reference(correlated=True).accepted_axes[0].correlated_models is True
    payload = _reference(correlated=True).model_dump(mode="json")
    payload["accepted_axes"][0]["correlated_models"] = False
    with pytest.raises(ValidationError, match="supporting model families"):
        AgentReferenceRecord.model_validate(payload)


def test_qualified_axis_requires_qualification_report() -> None:
    with pytest.raises(ValidationError, match="qualification_report_id"):
        AcceptedAxis(
            axis_id="is_forecast",
            value=True,
            tier="qualified",
            supporting_judgment_ids=["judgment-a", "judgment-r"],
            gate_version="gate-v1",
            admission_reason="Qualified independently.",
            correlated_models=False,
        )


def test_escalation_packet_only_emits_changed_pending_questions() -> None:
    high = _escalation(
        escalation_id="esc-high",
        policy_key="market-impact",
        impact_count=8,
        fingerprint="1" * 64,
    )
    unchanged = _escalation(
        escalation_id="esc-unchanged",
        policy_key="status-quo",
        impact_count=12,
        fingerprint="2" * 64,
        notified="2" * 64,
    )
    low = _escalation(
        escalation_id="esc-low",
        policy_key="mixed-type",
        impact_count=3,
        fingerprint="3" * 64,
    )
    packet = escalation_packet([low, unchanged, high])
    assert [item.escalation_id for item in packet] == ["esc-high", "esc-low"]
    assert all(len(item.examples) <= 2 for item in packet)


def test_policy_register_rejects_duplicate_versions(tmp_path) -> None:
    first = _escalation(
        escalation_id="esc-1",
        policy_key="market-impact",
        impact_count=2,
        fingerprint="4" * 64,
    )
    second = first.model_copy(update={"escalation_id": "esc-2"})
    path = tmp_path / "policy.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record.model_dump(mode="json"), sort_keys=True)
            for record in (first, second)
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate policy_key/evidence_fingerprint"):
        load_policy_escalations(path)


def test_agent_reference_reader_preserves_evidence_and_rejects_duplicate_ids(
    tmp_path,
) -> None:
    first = _reference()
    second = first.model_copy(
        update={"source": first.source.model_copy(update={"unit_id": "unit-2"})}
    )
    path = tmp_path / "references.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(record.model_dump(mode="json"), sort_keys=True)
            for record in (first, second)
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate reference_id"):
        load_agent_references(path)

    path.write_text(
        json.dumps(first.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    [loaded] = load_agent_references(path)
    assert loaded.judgments[0].call_id == "call-a"
    assert loaded.source.source_artifact.sha256 == "a" * 64


def test_role_prompts_are_present_and_distinct() -> None:
    hashes = {
        role: role_prompt_sha256(role)
        for role in ("annotator", "reviewer", "curator")
    }
    assert len(set(hashes.values())) == 3
    assert all(role_prompt_path(role).is_file() for role in hashes)
