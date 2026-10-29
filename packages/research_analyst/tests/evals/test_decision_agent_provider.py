"""Tests for the tool-free structured judgment provider adapter."""

from __future__ import annotations

import json

import pytest

from research_analysis_layer.evals.decision_agent_provider import (
    StructuredJudgmentProvider,
    TokenPricing,
)
from research_analysis_layer.evals.decision_agent_reference_run import (
    InvalidJudgmentResponse,
    JudgmentRequest,
)
from research_analysis_layer.evals.decision_agent_references import (
    AgentJudgment,
    AgentReferenceSource,
    ModelIdentity,
    role_prompt_path,
    role_prompt_sha256,
)
from research_analysis_layer.evals.decision_reviews import (
    SourceArtifactReference,
    sha256_text,
)
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    OpenAICompatibleAgentLlmClient,
    TokenUsage,
)


TAXONOMY = "pilot taxonomy"


def _identity(role: str) -> ModelIdentity:
    model = f"pinned-{role}-2026-10-23"
    return ModelIdentity(
        provider="structured-test",
        model=model,
        model_family=f"family-{role}",
        resolved_version=model,
    )


def _source() -> AgentReferenceSource:
    text = "Growth will slow next year."
    return AgentReferenceSource(
        source_id="opaque-source-1",
        document_id="doc-1",
        unit_id="unit-1",
        source_lineage_id="lineage-1",
        split="development",
        source_text=text,
        source_text_sha256=sha256_text(text),
        target_text=text,
        target_text_sha256=sha256_text(text),
        target_start=0,
        target_end=len(text),
        source_artifact=SourceArtifactReference(path="shadow.json", sha256="a" * 64),
    )


def _request(role: str = "annotator") -> JudgmentRequest:
    return JudgmentRequest(
        run_id="pilot-run-1",
        role=role,
        attempt_kind="initial",
        source=_source(),
        role_instructions=role_prompt_path(
            "reviewer" if role == "adjudicator" else role
        ).read_text(),
        role_prompt_sha256=role_prompt_sha256(
            "reviewer" if role == "adjudicator" else role
        ),
        taxonomy_version="taxonomy-v1",
        taxonomy_text=TAXONOMY,
        taxonomy_sha256=sha256_text(TAXONOMY),
        sampling={"reasoning_effort": "high"},
        disputed_axis_ids=["is_forecast"] if role == "adjudicator" else [],
        comparison_judgments=(
            [_prior("annotator", True), _prior("reviewer", False)]
            if role == "adjudicator"
            else []
        ),
    )


def _prior(role: str, value: bool) -> AgentJudgment:
    return AgentJudgment(
        judgment_id=f"prior-{role}",
        source_id="opaque-source-1",
        role=role,
        pass_kind="blind_first_pass",
        model=_identity(role),
        role_prompt_sha256=role_prompt_sha256(role),
        taxonomy_version="taxonomy-v1",
        taxonomy_sha256=sha256_text(TAXONOMY),
        call_id=f"call-{role}",
        created_at="2026-10-23T12:00:00Z",
        axes=[
            {
                "axis_id": "is_forecast",
                "state": "labeled",
                "value": value,
                "rationale": "Prior blind judgment.",
                "supporting_spans": [
                    {"start": 0, "end": 27, "text": "Growth will slow next year."}
                ],
            }
        ],
    )


class CapturingClient:
    reference_calls_are_single_attempt = True

    def __init__(self, *, model_used: str | None = None, malformed: bool = False) -> None:
        self.model_used = model_used
        self.malformed = malformed
        self.calls: list[dict] = []

    def reference_sampling_for_model(self, model: str) -> dict[str, str]:
        return {"reasoning_effort": "high"}

    def generate_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        payload = None if self.malformed else {
            "axes": [
                {
                    "axis_id": "is_forecast",
                    "state": "labeled",
                    "value": True,
                    "rationale": "The sentence describes a future outcome.",
                    "supporting_spans": [
                        {
                            "start": 0,
                            "end": 27,
                            "text": "Growth will slow next year.",
                        }
                    ],
                }
            ]
        }
        return AgentCallResult(
            raw_text=json.dumps(payload),
            parsed_output=payload,
            token_usage=TokenUsage(input_tokens=1000, output_tokens=200),
            model_used=self.model_used or kwargs["model"],
            stop_reason="stop",
        )


def _provider(client: CapturingClient) -> StructuredJudgmentProvider:
    return StructuredJudgmentProvider(
        client=client,
        role_models={role: _identity(role) for role in ("annotator", "reviewer", "adjudicator")},
        pricing_by_role={
            role: TokenPricing(
                input_usd_per_million=2,
                output_usd_per_million=10,
                source="test price card",
            )
            for role in ("annotator", "reviewer", "adjudicator")
        },
    )


def test_provider_exposes_no_tools_and_injects_trusted_metadata() -> None:
    client = CapturingClient()
    judgment = _provider(client).generate(_request())
    assert isinstance(judgment, AgentJudgment)
    assert judgment.role == "annotator"
    assert judgment.model == _identity("annotator")
    assert judgment.usage.input_tokens == 1000
    assert judgment.usage.output_tokens == 200
    assert judgment.usage.estimated_usd == pytest.approx(0.004)
    assert judgment.sampling == {"reasoning_effort": "high"}
    assert client.calls[0]["tools"] == []
    assert client.calls[0]["max_tool_calls"] == 0

    payload = json.loads(client.calls[0]["messages"][0]["content"])
    assert "labels" not in json.dumps(payload)
    assert "approval" not in json.dumps(payload)
    assert "prior_judgments" not in payload


def test_adjudicator_receives_axes_but_not_prior_model_identity() -> None:
    client = CapturingClient()
    judgment = _provider(client).generate(_request("adjudicator"))
    assert isinstance(judgment, AgentJudgment)
    assert judgment.pass_kind == "comparison"
    payload = json.loads(client.calls[0]["messages"][0]["content"])
    assert payload["disputed_axis_ids"] == ["is_forecast"]
    assert len(payload["prior_judgments"]) == 2
    assert "model" not in json.dumps(payload["prior_judgments"])
    assert "call_id" not in json.dumps(payload["prior_judgments"])


def test_malformed_output_preserves_paid_usage_for_schema_repair() -> None:
    with pytest.raises(InvalidJudgmentResponse) as raised:
        _provider(CapturingClient(malformed=True)).generate(_request())
    assert raised.value.usage.input_tokens == 1000
    assert raised.value.usage.output_tokens == 200
    assert raised.value.usage.estimated_usd == pytest.approx(0.004)


def test_resolved_model_must_match_the_frozen_pin() -> None:
    client = CapturingClient(model_used="silent-model-upgrade")
    with pytest.raises(RuntimeError, match="expected pinned"):
        _provider(client).generate(_request())


def test_unknown_pricing_stays_unknown_not_zero() -> None:
    client = CapturingClient()
    provider = StructuredJudgmentProvider(
        client=client,
        role_models={"annotator": _identity("annotator")},
    )
    judgment = provider.generate(_request())
    assert isinstance(judgment, AgentJudgment)
    assert judgment.usage.estimated_usd is None


def test_provider_rejects_clients_with_hidden_retries() -> None:
    client = CapturingClient()
    client.reference_calls_are_single_attempt = False
    with pytest.raises(ValueError, match="disable internal retries"):
        StructuredJudgmentProvider(
            client=client,
            role_models={"annotator": _identity("annotator")},
        )


def test_provider_rejects_sampling_that_is_not_effectively_applied() -> None:
    client = CapturingClient()
    client.reference_sampling_for_model = lambda model: {"reasoning_effort": "low"}
    with pytest.raises(RuntimeError, match="effective configuration"):
        _provider(client).generate(_request())


def test_openai_client_can_be_configured_for_harness_owned_retries() -> None:
    client = OpenAICompatibleAgentLlmClient(
        api_key="not-used",
        reasoning_effort="high",
        max_transport_retries=0,
    )
    provider = StructuredJudgmentProvider(
        client=client,
        role_models={"annotator": _identity("annotator")},
    )
    assert provider.client.reference_calls_are_single_attempt is True
    assert provider.client.reference_sampling_for_model("gpt-5-test") == {
        "reasoning_effort": "high"
    }
