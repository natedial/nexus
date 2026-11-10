"""Tests for the swappable model catalog and reference clients."""

from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from research_analysis_layer.evals.decision_agent_anthropic import (
    AnthropicReferenceClient,
)
from research_analysis_layer.evals.decision_agent_models import (
    ModelCatalog,
    build_role_clients,
    is_retryable_transport_error,
    load_model_catalog,
    parse_role_overrides,
    resolve_role_models,
)
from research_analysis_layer.services.agent_llm_client import (
    OpenAICompatibleAgentLlmClient,
)


def test_shipped_catalog_loads_with_distinct_default_families() -> None:
    catalog = load_model_catalog()
    resolved = resolve_role_models(catalog)
    families = {entry.model_family for entry in resolved.entries.values()}
    assert len(families) == 2
    assert set(resolved.entries) == {"annotator", "reviewer"}
    for role, pricing in resolved.pricing_by_role.items():
        assert pricing.input_usd_per_million > 0, role


def test_role_override_swaps_one_model() -> None:
    catalog = load_model_catalog()
    overrides = parse_role_overrides(["reviewer=openai:gpt-5.6-sol"])
    resolved = resolve_role_models(catalog, overrides)
    assert resolved.entries["reviewer"].model == "gpt-5.6-sol"
    assert resolved.entries["annotator"].model == catalog.models[
        catalog.roles["annotator"]
    ].model


def test_override_to_unknown_model_names_the_fix() -> None:
    with pytest.raises(ValueError, match="not in the catalog"):
        resolve_role_models(load_model_catalog(), {"reviewer": "openai:gpt-9"})


@pytest.mark.parametrize("flag", ["reviewer", "judge=openai:gpt-5.6-sol", "reviewer="])
def test_malformed_role_flags_are_rejected(flag: str) -> None:
    with pytest.raises(ValueError):
        parse_role_overrides([flag])


def test_catalog_keys_must_match_provider_and_model() -> None:
    with pytest.raises(ValueError, match="provider>:<model"):
        ModelCatalog.model_validate(
            {
                "roles": {"annotator": "x:y"},
                "models": {
                    "x:y": {
                        "provider": "x",
                        "model": "z",
                        "model_family": "f",
                        "input_usd_per_million": 1,
                        "output_usd_per_million": 1,
                        "pricing_source": "test",
                    }
                },
            }
        )


def test_registry_builds_one_client_per_entry_and_routes_roles() -> None:
    catalog = load_model_catalog()
    resolved = resolve_role_models(
        catalog, {"reviewer": catalog.roles["annotator"]}
    )
    built: list[str] = []

    def fake_builder(entry):
        built.append(entry.model)
        return SimpleNamespace(model=entry.model)

    provider = resolved.entries["annotator"].provider
    clients = build_role_clients(resolved, builders={provider: fake_builder})
    assert len(built) == 1
    assert clients["annotator"] is clients["reviewer"]


def test_registry_rejects_unknown_provider() -> None:
    resolved = resolve_role_models(load_model_catalog())
    with pytest.raises(ValueError, match="no client builder"):
        build_role_clients(resolved, builders={})


def test_missing_api_key_fails_before_any_call(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    catalog = load_model_catalog()
    resolved = resolve_role_models(catalog, {"annotator": "openai:gpt-5.6-terra"})
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_role_clients(resolved)


def test_openai_reference_client_reports_served_model(monkeypatch) -> None:
    client = OpenAICompatibleAgentLlmClient(
        api_key="test",
        max_transport_retries=0,
        report_response_model=True,
    )
    monkeypatch.setattr(
        client,
        "_make_request",
        lambda request, timeout: {
            "model": "gpt-5.6-terra-2026-08-01",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "choices": [
                {"finish_reason": "stop", "message": {"content": '{"axes": []}'}}
            ],
        },
    )
    result = client.generate_with_tools(
        system_prompt="s", messages=[], tools=[], model="gpt-5.6-terra", max_tool_calls=0
    )
    assert result.model_used == "gpt-5.6-terra-2026-08-01"


def test_single_attempt_openai_client_surfaces_rate_limits(monkeypatch) -> None:
    client = OpenAICompatibleAgentLlmClient(api_key="test", max_transport_retries=0)

    def raise_429(request, timeout):
        raise urllib.error.HTTPError("u", 429, "rate", {}, io.BytesIO(b""))

    monkeypatch.setattr(client, "_make_request", raise_429)
    with pytest.raises(urllib.error.HTTPError) as raised:
        client.generate_with_tools(
            system_prompt="s", messages=[], tools=[], model="m", max_tool_calls=0
        )
    assert is_retryable_transport_error(raised.value)


def test_client_errors_are_not_retryable() -> None:
    error = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b""))
    assert not is_retryable_transport_error(error)
    assert not is_retryable_transport_error(ValueError("schema"))


class _FakeMessages:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text='```json\n{"axes": []}\n```'),
            ],
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=40,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            model="claude-sonnet-5-5",
            stop_reason="end_turn",
        )


def test_anthropic_client_applies_effort_and_parses_text_only() -> None:
    messages = _FakeMessages()
    client = AnthropicReferenceClient(
        sampling_by_model={"claude-sonnet-5-5": {"effort": "medium"}},
        sdk_client=SimpleNamespace(messages=messages),
    )
    assert client.reference_calls_are_single_attempt is True
    assert client.reference_sampling_for_model("claude-sonnet-5-5") == {
        "effort": "medium"
    }
    result = client.generate_with_tools(
        system_prompt="system",
        messages=[{"role": "user", "content": json.dumps({"x": 1})}],
        tools=[],
        model="claude-sonnet-5-5",
        max_tool_calls=0,
        timeout_seconds=30,
    )
    assert messages.kwargs["output_config"] == {"effort": "medium"}
    assert messages.kwargs["system"] == "system"
    assert "tools" not in messages.kwargs
    assert result.parsed_output == {"axes": []}
    assert result.token_usage.input_tokens == 120
    assert result.model_used == "claude-sonnet-5-5"


def test_anthropic_client_refuses_tools_and_unknown_sampling() -> None:
    client = AnthropicReferenceClient(sdk_client=SimpleNamespace(messages=_FakeMessages()))
    with pytest.raises(ValueError, match="must not expose tools"):
        client.generate_with_tools(
            system_prompt="s", messages=[], tools=[{"name": "t"}], model="m"
        )
    with pytest.raises(ValueError, match="sampling keys"):
        AnthropicReferenceClient(
            sampling_by_model={"m": {"temperature": 0}},
            sdk_client=SimpleNamespace(messages=_FakeMessages()),
        )
