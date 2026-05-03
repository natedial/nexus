from types import SimpleNamespace

import pytest

from src.llm import LLMClient, ModelConfig


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
