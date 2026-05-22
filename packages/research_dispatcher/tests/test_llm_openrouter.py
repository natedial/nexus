from types import SimpleNamespace

import pytest

from src.llm import LLMClient, LLMOutputParseError, ModelConfig


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="openrouter ok"))]
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeCompletions())


def test_openrouter_provider_uses_openai_compatible_request(monkeypatch):
    llm = LLMClient(openrouter_api_key="sk-or-test")
    fake_client = _FakeClient()
    monkeypatch.setattr(type(llm), "openrouter", property(lambda self: fake_client))

    out = llm.generate(
        config=ModelConfig(
            provider="openrouter",
            model="openai/gpt-5.2",
            max_tokens=123,
            temperature=0,
        ),
        system="System",
        user="User",
    )

    assert out == "openrouter ok"
    assert fake_client.chat.completions.kwargs["model"] == "openai/gpt-5.2"
    assert fake_client.chat.completions.kwargs["max_tokens"] == 123
    assert fake_client.chat.completions.kwargs["messages"][0]["role"] == "system"


def test_openrouter_requires_api_key():
    llm = LLMClient()

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        llm.generate(
            config=ModelConfig(provider="openrouter", model="openai/gpt-5.2"),
            system="System",
            user="User",
        )


def test_generate_json_parses_plain_and_fenced_json(monkeypatch):
    llm = LLMClient(openai_api_key="sk-test")
    responses = iter(
        [
            'prefix {"ok": true}',
            '```json\n{"ok": true}\n```',
        ]
    )
    monkeypatch.setattr(llm, "generate", lambda **kwargs: next(responses))

    config = ModelConfig(
        provider="openai",
        model="gpt-5-mini",
        parse_strategy="strict_json_object",
    )

    assert llm.generate_json(config=config, system="System", user="User") == {"ok": True}
    assert llm.generate_json(config=config, system="System", user="User") == {"ok": True}


def test_generate_json_strips_visible_reasoning(monkeypatch):
    llm = LLMClient(openai_api_key="sk-test")
    monkeypatch.setattr(
        llm,
        "generate",
        lambda **kwargs: "<think>private reasoning</think>{\"ok\": true}",
    )

    assert llm.generate_json(
        config=ModelConfig(provider="openai", model="gpt-5-mini"),
        system="System",
        user="User",
    ) == {"ok": True}


def test_generate_json_rejects_unterminated_visible_reasoning(monkeypatch):
    llm = LLMClient(openai_api_key="sk-test")
    monkeypatch.setattr(llm, "generate", lambda **kwargs: "<think>unterminated")

    with pytest.raises(LLMOutputParseError, match="unterminated"):
        llm.generate_json(
            config=ModelConfig(provider="openai", model="gpt-5-mini"),
            system="System",
            user="User",
        )


def test_openai_compatible_extractor_handles_structured_text_parts():
    llm = LLMClient()
    message = SimpleNamespace(
        content=[
            {"type": "reasoning", "text": "ignore?"},
            {"type": "text", "text": "{\"ok\":"},
            SimpleNamespace(type="output_text", text=" true}"),
        ]
    )

    assert llm._extract_openai_compatible_text(message) == '{"ok": true}'


def test_anthropic_skips_thinking_blocks(monkeypatch):
    llm = LLMClient(anthropic_api_key="sk-ant-test")

    class _FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(
                content=[
                    SimpleNamespace(type="thinking", thinking="hidden"),
                    SimpleNamespace(type="text", text='{"ok": true}'),
                ]
            )

    fake_client = SimpleNamespace(messages=_FakeMessages())
    monkeypatch.setattr(type(llm), "anthropic", property(lambda self: fake_client))

    out = llm.generate(
        config=ModelConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            extended_thinking=None,
        ),
        system="System",
        user="User",
    )

    assert out == '{"ok": true}'


def test_openrouter_sends_reasoning_effort_only_when_configured(monkeypatch):
    llm = LLMClient(openrouter_api_key="sk-or-test")
    fake_client = _FakeClient()
    monkeypatch.setattr(type(llm), "openrouter", property(lambda self: fake_client))

    llm.generate(
        config=ModelConfig(
            provider="openrouter",
            model="openai/gpt-5.2",
            reasoning_effort="medium",
        ),
        system="System",
        user="User",
    )

    assert fake_client.chat.completions.kwargs["reasoning_effort"] == "medium"
