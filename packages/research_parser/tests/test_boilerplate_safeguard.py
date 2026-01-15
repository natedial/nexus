from src.extraction.boilerplate import strip_boilerplate
from src.llm import ModelConfig


class FakeClient:
    def __init__(self, response: str):
        self._response = response

    def generate(self, config, system, user):
        return self._response


def test_strip_boilerplate_falls_back_on_excessive_reduction():
    text = "A" * 10000
    response = "B" * 500
    client = FakeClient(response)
    config = ModelConfig(provider="openai", model="test")

    cleaned = strip_boilerplate(client, text, config)

    assert cleaned == text


def test_strip_boilerplate_keeps_reasonable_reduction():
    text = "A" * 10000
    response = "B" * 1500
    client = FakeClient(response)
    config = ModelConfig(provider="openai", model="test")

    cleaned = strip_boilerplate(client, text, config)

    assert cleaned == response
