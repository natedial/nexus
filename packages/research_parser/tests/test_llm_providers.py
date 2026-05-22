from types import SimpleNamespace

import pytest

from src.llm import LLMClient, ModelConfig


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


class _FakeResponses:
    def __init__(self):
        self.kwargs = None
        self.calls = []

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='{"ok": true}')


class _FakeOpenAIClient(_FakeClient):
    def __init__(self):
        super().__init__()
        self.responses = _FakeResponses()


class _SequencedCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))])


def test_generate_routes_to_openai_compatible_provider(monkeypatch):
    fake_client = _FakeClient()
    llm = LLMClient(groq_api_key="gsk-test")
    monkeypatch.setattr(llm, "_openai_compatible_client", lambda provider: fake_client)

    config = ModelConfig(provider="groq", model="openai/gpt-oss-20b")
    out = llm.generate(
        config=config,
        system="Return JSON.",
        user="test",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "resp", "schema": {"type": "object"}},
        },
    )

    assert out == '{"ok": true}'
    assert fake_client.chat.completions.kwargs is not None
    assert fake_client.chat.completions.kwargs["model"] == "openai/gpt-oss-20b"
    assert "messages" in fake_client.chat.completions.kwargs


def test_groq_provider_requires_api_key():
    llm = LLMClient()
    config = ModelConfig(provider="groq", model="openai/gpt-oss-20b")

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        llm.generate(config=config, system="sys", user="user")


def test_openrouter_provider_requires_api_key():
    llm = LLMClient()
    config = ModelConfig(provider="openrouter", model="openai/gpt-5.2")

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        llm.generate(config=config, system="sys", user="user")


def test_openrouter_routes_to_openai_compatible_client(monkeypatch):
    fake_client = _FakeClient()
    llm = LLMClient(openrouter_api_key="sk-or-test")
    monkeypatch.setattr(llm, "_openai_compatible_client", lambda provider: fake_client)

    config = ModelConfig(provider="openrouter", model="openai/gpt-5.2")
    out = llm.generate(
        config=config,
        system="Return JSON.",
        user="test",
        response_format={"type": "json_object"},
    )

    assert out == '{"ok": true}'
    assert fake_client.chat.completions.kwargs["model"] == "openai/gpt-5.2"
    assert fake_client.chat.completions.kwargs["response_format"] == {"type": "json_object"}


def test_generate_uses_fallback_when_primary_fails(monkeypatch):
    llm = LLMClient(groq_api_key="gsk-test", deepinfra_api_key="di-test")
    calls = []

    def _fake_generate_single(config, system, user, response_format=None):
        calls.append((config.provider, config.model))
        if config.provider == "groq":
            raise RuntimeError("rate limit")
        return '{"ok": true, "provider": "deepinfra"}'

    monkeypatch.setattr(llm, "_generate_single", _fake_generate_single)
    config = ModelConfig(
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback=[
            ModelConfig(
                provider="deepinfra",
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            )
        ],
    )

    out = llm.generate(config=config, system="sys", user="user")
    assert out == '{"ok": true, "provider": "deepinfra"}'
    assert calls == [
        ("groq", "openai/gpt-oss-20b"),
        ("deepinfra", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ]


def test_generate_raises_last_error_when_all_attempts_fail(monkeypatch):
    llm = LLMClient(groq_api_key="gsk-test", deepinfra_api_key="di-test")

    def _always_fail(config, system, user, response_format=None):
        raise RuntimeError(f"failed:{config.provider}")

    monkeypatch.setattr(llm, "_generate_single", _always_fail)
    config = ModelConfig(
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback=[
            ModelConfig(
                provider="deepinfra",
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            )
        ],
    )

    with pytest.raises(RuntimeError, match="failed:deepinfra"):
        llm.generate(config=config, system="sys", user="user")


def test_model_config_parses_fallback_from_dict():
    cfg = ModelConfig.from_dict(
        {
            "provider": "groq",
            "model": "openai/gpt-oss-20b",
            "max_tokens": 128,
            "fallback": [
                {
                    "provider": "deepinfra",
                    "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                    "max_tokens": 256,
                }
            ],
        }
    )

    assert cfg.provider == "groq"
    assert cfg.fallback is not None
    assert len(cfg.fallback) == 1
    assert cfg.fallback[0].provider == "deepinfra"


def test_model_config_parses_reasoning_effort_from_dict():
    cfg = ModelConfig.from_dict(
        {
            "provider": "openai",
            "model": "gpt-5.2",
            "reasoning_effort": "high",
        }
    )

    assert cfg.reasoning_effort == "high"


def test_openai_responses_request_includes_configured_reasoning_effort():
    fake_client = _FakeOpenAIClient()
    llm = LLMClient(openai_api_key="sk-test")
    llm._openai_client = fake_client

    config = ModelConfig(
        provider="openai",
        model="gpt-5.2",
        max_tokens=512,
        reasoning_effort="high",
    )
    out = llm.generate(
        config=config,
        system="Return JSON.",
        user="test",
    )

    assert out == '{"ok": true}'
    assert fake_client.responses.kwargs["reasoning"] == {"effort": "high"}
    assert fake_client.responses.kwargs["max_output_tokens"] == 512
    assert "temperature" not in fake_client.responses.kwargs


def test_openai_responses_request_sends_structured_output_via_text_format():
    fake_client = _FakeOpenAIClient()
    llm = LLMClient(openai_api_key="sk-test")
    llm._openai_client = fake_client

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "structured_response",
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }

    out = llm.generate(
        config=ModelConfig(
            provider="openai",
            model="gpt-5.2",
            max_tokens=512,
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="test",
        response_format=response_format,
    )

    assert out == '{"ok": true}'
    assert "response_format" not in fake_client.responses.kwargs
    assert fake_client.responses.kwargs["text"] == {
        "format": {
            "type": "json_schema",
            "name": "structured_response",
            "schema": response_format["json_schema"]["schema"],
            "strict": True,
        }
    }


def test_openai_responses_request_omits_reasoning_when_not_configured():
    fake_client = _FakeOpenAIClient()
    llm = LLMClient(openai_api_key="sk-test")
    llm._openai_client = fake_client

    config = ModelConfig(
        provider="openai",
        model="gpt-5.2",
        max_tokens=512,
    )
    out = llm.generate(
        config=config,
        system="Return JSON.",
        user="test",
    )

    assert out == '{"ok": true}'
    assert "reasoning" not in fake_client.responses.kwargs
    assert fake_client.responses.kwargs["temperature"] == 0


def test_generate_uses_fallback_when_primary_returns_empty(monkeypatch):
    llm = LLMClient(groq_api_key="gsk-test", deepinfra_api_key="di-test")
    calls = []

    def _fake_generate_single(config, system, user, response_format=None):
        calls.append(config.provider)
        if config.provider == "groq":
            return ""
        return '{"ok": true, "provider": "deepinfra"}'

    monkeypatch.setattr(llm, "_generate_single", _fake_generate_single)
    config = ModelConfig(
        provider="groq",
        model="openai/gpt-oss-20b",
        fallback=[
            ModelConfig(
                provider="deepinfra",
                model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
            )
        ],
    )

    out = llm.generate(config=config, system="sys", user="user")
    assert out == '{"ok": true, "provider": "deepinfra"}'
    assert calls == ["groq", "deepinfra"]


def test_deepinfra_agentic_models_force_json_object_and_disable_tools():
    llm = LLMClient(deepinfra_api_key="di-test")
    kwargs = llm._openai_compatible_request_kwargs(
        ModelConfig(provider="deepinfra", model="MiniMaxAI/MiniMax-M2.5"),
        system="Return JSON.",
        user="test",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "resp", "schema": {"type": "object"}},
        },
    )

    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["tool_choice"] == "none"
    assert kwargs["reasoning_effort"] == "none"


def test_non_agentic_openai_compatible_models_keep_requested_response_format():
    llm = LLMClient(deepinfra_api_key="di-test")
    requested = {
        "type": "json_schema",
        "json_schema": {"name": "resp", "schema": {"type": "object"}},
    }

    kwargs = llm._openai_compatible_request_kwargs(
        ModelConfig(provider="deepinfra", model="moonshotai/Kimi-K2-Instruct-0905"),
        system="Return JSON.",
        user="test",
        response_format=requested,
    )

    assert kwargs["response_format"] == requested
    assert "tool_choice" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_openrouter_request_includes_configured_reasoning():
    llm = LLMClient(openrouter_api_key="sk-or-test")
    kwargs = llm._openai_compatible_request_kwargs(
        ModelConfig(
            provider="openrouter",
            model="openai/gpt-5.2",
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="test",
        response_format={"type": "json_object"},
    )

    assert kwargs["extra_body"] == {
        "reasoning": {"effort": "high", "exclude": True}
    }
    assert "reasoning_effort" not in kwargs


def test_openrouter_retry_drops_reasoning_before_response_format(monkeypatch):
    completions = _SequencedCompletions(
        [
            RuntimeError("reasoning is not supported"),
            '{"ok": true}',
        ]
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LLMClient(openrouter_api_key="sk-or-test")
    monkeypatch.setattr(llm, "_openai_compatible_client", lambda provider: fake_client)

    out = llm.generate(
        config=ModelConfig(
            provider="openrouter",
            model="openai/gpt-5.2",
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="test",
        response_format={"type": "json_object"},
    )

    assert out == '{"ok": true}'
    assert len(completions.calls) == 2
    assert completions.calls[0]["response_format"] == {"type": "json_object"}
    assert "extra_body" in completions.calls[0]
    assert completions.calls[1]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in completions.calls[1]


def test_openrouter_retry_drops_response_format_after_second_failure(monkeypatch):
    completions = _SequencedCompletions(
        [
            RuntimeError("reasoning is not supported"),
            RuntimeError("response_format is not supported"),
            '{"ok": true}',
        ]
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = LLMClient(openrouter_api_key="sk-or-test")
    monkeypatch.setattr(llm, "_openai_compatible_client", lambda provider: fake_client)

    out = llm.generate(
        config=ModelConfig(
            provider="openrouter",
            model="openai/gpt-5.2",
            reasoning_effort="high",
        ),
        system="Return JSON.",
        user="test",
        response_format={"type": "json_object"},
    )

    assert out == '{"ok": true}'
    assert len(completions.calls) == 3
    assert completions.calls[1]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in completions.calls[1]
    assert "response_format" not in completions.calls[2]
    assert "extra_body" not in completions.calls[2]
