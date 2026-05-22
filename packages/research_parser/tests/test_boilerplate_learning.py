import json

from src.extraction import boilerplate
from src.llm import ModelConfig


class _FakeClient:
    def __init__(self, response: str):
        self._response = response

    def generate(self, config, system, user):
        return self._response


def _build_text() -> str:
    return "\n".join([f"Research line {i}" for i in range(1, 80)])


def test_llm_fallback_persists_learning_artifact(monkeypatch, tmp_path):
    learned_path = tmp_path / "llm_boilerplate_artifacts.jsonl"
    monkeypatch.setattr(boilerplate, "LEARNED_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(boilerplate, "LEARNED_ARTIFACTS_PATH", learned_path)
    boilerplate._load_learned_headers.cache_clear()

    text = _build_text()
    # Place disclosure header too early for deterministic truncation to trigger.
    lines = text.splitlines()
    lines.insert(35, "Important Disclosures:")
    lines.insert(36, "Analyst disclosures and conflict of interest statement.")
    lines.insert(37, "Regulatory disclosures and distribution information.")
    lines.insert(38, "Copyright notice.")
    text = "\n".join(lines)
    # Simulate LLM trimming from the inserted disclosure block onward.
    response = "\n".join(lines[:35])
    cleaned = boilerplate.strip_boilerplate(
        client=_FakeClient(response),
        text=text,
        config=ModelConfig(provider="groq", model="openai/gpt-oss-20b"),
        deterministic_only=False,
        document_name="2026-03-02_GS_macro_note.pdf",
        artifact_dir=tmp_path / "doc_artifact",
    )

    assert cleaned == response
    assert learned_path.exists()

    lines = learned_path.read_text().splitlines()
    assert lines
    rec = json.loads(lines[-1])
    assert rec["source_key"] == "gs"
    assert rec["candidate_headers"]
    assert (tmp_path / "doc_artifact" / "boilerplate_llm_artifact.json").exists()


def test_learned_headers_are_loaded_from_artifacts(monkeypatch, tmp_path):
    learned_path = tmp_path / "llm_boilerplate_artifacts.jsonl"
    learned_path.write_text(
        json.dumps(
            {
                "source_key": "gs",
                "candidate_headers": ["important legal terms", "research disclosures"],
            }
        )
        + "\n"
    )
    monkeypatch.setattr(boilerplate, "LEARNED_ARTIFACTS_PATH", learned_path)
    boilerplate._load_learned_headers.cache_clear()

    loaded = boilerplate._load_learned_headers()
    assert "gs" in loaded
    assert "important legal terms" in loaded["gs"]
