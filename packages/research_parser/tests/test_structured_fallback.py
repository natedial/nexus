import json

from src.extraction.metadata import extract_metadata
from src.llm import ModelConfig


class _FakeLLMClient:
    def __init__(self, responses: dict[tuple[str, str], str]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def model_attempts(self, config: ModelConfig) -> list[ModelConfig]:
        attempts = [config]
        attempts.extend(config.fallback or [])
        return attempts

    def generate_once(self, config: ModelConfig, system: str, user: str, response_format=None) -> str:
        key = (config.provider, config.model)
        self.calls.append(key)
        return self.responses[key]


def test_extract_metadata_falls_back_after_invalid_primary_response():
    client = _FakeLLMClient(
        {
            ("groq", "openai/gpt-oss-20b"): '{"source": ',
            (
                "deepinfra",
                "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            ): json.dumps(
                {
                    "source": "J.P. Morgan",
                    "source_date": "2026-03-06",
                    "area": "USD",
                    "region": "US",
                    "asset_focus": "rates",
                    "publisher": "J.P. Morgan",
                    "number_pages": None,
                    "keywords": ["treasury"],
                }
            ),
        }
    )
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

    metadata = extract_metadata(
        client=client,
        text="J.P. Morgan research dated 2026-03-06",
        config=config,
    )

    assert metadata.source == "J.P. Morgan"
    assert metadata.area == "USD"
    assert client.calls == [
        ("groq", "openai/gpt-oss-20b"),
        ("deepinfra", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ]
