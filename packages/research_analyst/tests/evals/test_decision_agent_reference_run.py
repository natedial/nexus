"""Tests for the checkpointed agent-reference execution harness."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    InvalidJudgmentResponse,
    JudgmentRequest,
    ReferenceBatchHarness,
    ResourceLimits,
    RetryableProviderError,
)
from research_analysis_layer.evals.decision_agent_references import (
    AgentJudgment,
    AgentReferenceRecord,
    AgentReferenceSource,
    AxisJudgment,
    CallUsage,
    ModelIdentity,
    SupportingSpan,
    role_prompt_sha256,
)
from research_analysis_layer.evals.decision_reviews import (
    SourceArtifactReference,
    sha256_text,
)


NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
TAXONOMY = "statement_type and sparse decision axes v1"


def _identity(role: str) -> ModelIdentity:
    return ModelIdentity(
        provider="scripted",
        model=f"{role}-model",
        model_family=f"{role}-family",
        resolved_version=f"{role}-model-2026-10-22",
    )


def _source(*, source_id: str = "source-1", lineage: str = "lineage-1") -> AgentReferenceSource:
    source_text = "Context. Growth will slow next year. End."
    target = "Growth will slow next year."
    start = source_text.index(target)
    return AgentReferenceSource(
        source_id=source_id,
        document_id="doc-1",
        unit_id=f"unit-{source_id}",
        source_lineage_id=lineage,
        split="development",
        source_text=source_text,
        source_text_sha256=sha256_text(source_text),
        target_text=target,
        target_text_sha256=sha256_text(target),
        target_start=start,
        target_end=start + len(target),
        source_artifact=SourceArtifactReference(
            path=f"private/{source_id}.json",
            sha256="a" * 64,
        ),
    )


def _config(*, max_requests: int = 8, execution_mode: str = "scripted") -> HarnessConfig:
    role_models = {
        role: _identity(role) for role in ("annotator", "reviewer", "adjudicator")
    }
    return HarnessConfig(
        run_id="run-1",
        execution_mode=execution_mode,
        taxonomy_version="taxonomy-v1",
        taxonomy_text=TAXONOMY,
        taxonomy_sha256=sha256_text(TAXONOMY),
        gate_version="gate-v1",
        role_models=role_models,
        limits=ResourceLimits(
            max_requests=max_requests,
            max_input_tokens=1000,
            max_output_tokens=1000,
            max_elapsed_seconds=30,
            max_estimated_usd=1.0,
        ),
    )


def _judgment(
    request: JudgmentRequest,
    *,
    value: bool = True,
    call_suffix: str = "1",
) -> AgentJudgment:
    target = request.source.target_text
    return AgentJudgment(
        judgment_id=f"judgment-{request.role}-{call_suffix}",
        source_id=request.source.source_id,
        role=request.role,
        pass_kind=(
            "comparison" if request.role == "adjudicator" else "blind_first_pass"
        ),
        model=_identity(request.role),
        role_prompt_sha256=role_prompt_sha256(
            "reviewer" if request.role == "adjudicator" else request.role
        ),
        taxonomy_version=request.taxonomy_version,
        taxonomy_sha256=request.taxonomy_sha256,
        call_id=f"call-{request.role}-{call_suffix}",
        created_at=NOW,
        usage=CallUsage(input_tokens=10, output_tokens=5, estimated_usd=0.01),
        axes=[
            AxisJudgment(
                axis_id="is_forecast",
                state="labeled",
                value=value,
                rationale="The sentence makes a future prediction.",
                supporting_spans=[
                    SupportingSpan(start=0, end=len(target), text=target)
                ],
            )
        ],
    )


class CapturingProvider:
    def __init__(self, *, disagree: bool = False) -> None:
        self.disagree = disagree
        self.requests: list[JudgmentRequest] = []

    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        value = not (self.disagree and request.role == "reviewer")
        return _judgment(request, value=value, call_suffix=str(len(self.requests)))


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_blind_first_passes_are_isolated_and_agreement_is_admitted(tmp_path) -> None:
    provider = CapturingProvider()
    output = tmp_path / "run"
    ReferenceBatchHarness(provider).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
    )

    first_passes = [
        request for request in provider.requests if request.role in {"annotator", "reviewer"}
    ]
    assert len(first_passes) == 2
    assert all(request.comparison_judgments == [] for request in first_passes)
    assert all(request.disputed_axis_ids == [] for request in first_passes)
    assert json.loads((output / "manifest.json").read_text())["status"] == "complete"

    [payload] = _rows(output / "references.jsonl")
    record = AgentReferenceRecord.model_validate(payload)
    assert [(axis.axis_id, axis.value) for axis in record.accepted_axes] == [
        ("is_forecast", True)
    ]
    assert record.lifecycle == "provisional"


def test_disagreement_gets_one_comparison_call_and_stays_quarantined(tmp_path) -> None:
    provider = CapturingProvider(disagree=True)
    output = tmp_path / "run"
    ReferenceBatchHarness(provider).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
    )

    adjudicator_requests = [r for r in provider.requests if r.role == "adjudicator"]
    assert len(adjudicator_requests) == 1
    assert adjudicator_requests[0].disputed_axis_ids == ["is_forecast"]
    assert len(adjudicator_requests[0].comparison_judgments) == 2
    [payload] = _rows(output / "references.jsonl")
    record = AgentReferenceRecord.model_validate(payload)
    assert record.accepted_axes == []
    assert "third judgment recorded" in record.quarantined_axes["is_forecast"]
    assert len(_rows(output / "adjudications.jsonl")) == 1


def test_request_cap_checkpoints_without_calling_reviewer(tmp_path) -> None:
    provider = CapturingProvider()
    output = tmp_path / "run"
    ReferenceBatchHarness(provider).run(
        output_dir=output,
        sources=[_source()],
        config=_config(max_requests=1),
    )

    assert [request.role for request in provider.requests] == ["annotator"]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "incomplete"
    assert "request cap" in manifest["stop_reason"]
    assert manifest["usage"]["requests"] == 1
    assert _rows(output / "references.jsonl") == []


class InterruptingProvider(CapturingProvider):
    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        if request.role == "reviewer":
            raise RuntimeError("simulated interruption")
        return _judgment(request, call_suffix=str(len(self.requests)))


def test_interrupted_run_resumes_only_unfinished_work(tmp_path) -> None:
    output = tmp_path / "run"
    first = InterruptingProvider()
    harness = ReferenceBatchHarness(first)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        harness.run(output_dir=output, sources=[_source()], config=_config())

    assert [request.role for request in first.requests] == ["annotator", "reviewer"]
    second = CapturingProvider()
    ReferenceBatchHarness(second).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
        resume=True,
    )
    assert [request.role for request in second.requests] == ["reviewer"]
    assert json.loads((output / "manifest.json").read_text())["status"] == "complete"
    assert len(_rows(output / "judgments.jsonl")) == 2


def test_resume_rejects_tampered_frozen_sources(tmp_path) -> None:
    output = tmp_path / "run"
    ReferenceBatchHarness(CapturingProvider()).run(
        output_dir=output,
        sources=[_source()],
        config=_config(max_requests=1),
    )
    [stored] = _rows(output / "sources.jsonl")
    stored["document_type"] = "tampered"
    (output / "sources.jsonl").write_text(
        json.dumps(stored, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="frozen hash"):
        ReferenceBatchHarness(CapturingProvider()).run(
            output_dir=output,
            sources=[_source()],
            config=_config(max_requests=1),
            resume=True,
        )


class RepairingProvider(CapturingProvider):
    def generate(self, request: JudgmentRequest) -> AgentJudgment | dict[str, Any]:
        self.requests.append(request)
        if len(self.requests) == 1:
            return {"not": "a judgment"}
        return _judgment(request, call_suffix=str(len(self.requests)))


def test_one_schema_repair_uses_unchanged_source_and_taxonomy(tmp_path) -> None:
    provider = RepairingProvider()
    output = tmp_path / "run"
    ReferenceBatchHarness(provider).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
    )
    assert [request.attempt_kind for request in provider.requests[:2]] == [
        "initial",
        "schema_repair",
    ]
    assert provider.requests[0].source == provider.requests[1].source
    assert provider.requests[0].taxonomy_sha256 == provider.requests[1].taxonomy_sha256
    attempts = _rows(output / "attempts.jsonl")
    assert attempts[0]["status"] == "schema_error"


class PaidRepairingProvider(CapturingProvider):
    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise InvalidJudgmentResponse(
                "paid malformed response",
                usage=CallUsage(
                    input_tokens=40,
                    output_tokens=10,
                    estimated_usd=0.02,
                ),
            )
        return _judgment(request, call_suffix=str(len(self.requests)))


def test_schema_repair_counts_usage_from_the_invalid_attempt(tmp_path) -> None:
    output = tmp_path / "run"
    ReferenceBatchHarness(PaidRepairingProvider()).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
    )
    usage = json.loads((output / "manifest.json").read_text())["usage"]
    # Invalid attempt (40/10/$0.02) plus two successful calls (10/5/$0.01 each).
    assert usage["requests"] == 3
    assert usage["input_tokens"] == 60
    assert usage["output_tokens"] == 20
    assert usage["estimated_usd"] == pytest.approx(0.04)


class AlwaysRetryableProvider(CapturingProvider):
    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        raise RetryableProviderError("temporary transport failure")


def test_transport_retries_are_bounded_at_two(tmp_path) -> None:
    provider = AlwaysRetryableProvider()
    output = tmp_path / "run"
    with pytest.raises(RetryableProviderError):
        ReferenceBatchHarness(provider).run(
            output_dir=output,
            sources=[_source()],
            config=_config(),
        )
    assert [request.attempt_kind for request in provider.requests] == [
        "initial",
        "transport_retry",
        "transport_retry",
    ]
    assert json.loads((output / "manifest.json").read_text())["status"] == "incomplete"


class ReusedIdentityProvider(CapturingProvider):
    def generate(self, request: JudgmentRequest) -> AgentJudgment:
        self.requests.append(request)
        judgment = _judgment(request, call_suffix="reused")
        if request.role == "reviewer":
            judgment.judgment_id = "judgment-annotator-reused"
            judgment.call_id = "call-annotator-reused"
        return judgment


def test_call_and_judgment_ids_are_unique_across_the_batch(tmp_path) -> None:
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="reused judgment_id"):
        ReferenceBatchHarness(ReusedIdentityProvider()).run(
            output_dir=output,
            sources=[_source()],
            config=_config(),
        )
    assert len(_rows(output / "judgments.jsonl")) == 1


def test_output_directory_and_finalized_run_are_immutable(tmp_path) -> None:
    output = tmp_path / "run"
    output.mkdir()
    with pytest.raises(FileExistsError):
        ReferenceBatchHarness(CapturingProvider()).run(
            output_dir=output,
            sources=[_source()],
            config=_config(),
        )

    output.rmdir()
    ReferenceBatchHarness(CapturingProvider()).run(
        output_dir=output,
        sources=[_source()],
        config=_config(),
    )
    with pytest.raises(ValueError, match="immutable"):
        ReferenceBatchHarness(CapturingProvider()).run(
            output_dir=output,
            sources=[_source()],
            config=_config(),
            resume=True,
        )


def test_live_config_requires_dollar_cap_and_duplicate_lineage_is_rejected(
    tmp_path,
) -> None:
    payload = _config().model_dump(mode="json")
    payload["execution_mode"] = "live"
    payload["limits"]["max_estimated_usd"] = None
    with pytest.raises(ValidationError, match="max_estimated_usd"):
        HarnessConfig.model_validate(payload)

    first = _source(source_id="source-1", lineage="same-lineage")
    second = _source(source_id="source-2", lineage="same-lineage").model_copy(
        update={"unit_id": "different-unit"}
    )
    with pytest.raises(ValueError, match="duplicate lineage"):
        ReferenceBatchHarness(CapturingProvider()).run(
            output_dir=tmp_path / "duplicate",
            sources=[first, second],
            config=_config(),
        )
