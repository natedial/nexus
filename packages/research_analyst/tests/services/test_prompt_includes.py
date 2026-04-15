"""Tests for the {{include: path}} resolver in AgentRegistry.load_prompt."""

from pathlib import Path
import textwrap

import pytest

from research_analysis_layer.services.agent_registry import AgentRegistry


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_load_prompt_resolves_sibling_include(tmp_path):
    agents_dir = tmp_path / "prompts" / "agents"
    components_dir = agents_dir / "_components"
    _write(components_dir, "fragment.md", "SHARED FRAGMENT BODY")
    _write(
        agents_dir,
        "thesis.md",
        textwrap.dedent(
            """
            # Thesis Agent

            Pre-text.

            {{include: _components/fragment.md}}

            Post-text.
            """
        ).strip(),
    )
    config = tmp_path / "agent_config.yaml"
    config.write_text(
        textwrap.dedent(
            """
            agents:
              thesis:
                prompt_path: prompts/agents/thesis.md
                model:
                  primary: claude-sonnet-4-20250514
                  fallback: claude-haiku-4-20250514
                output_schema: DocumentAngle
            """
        ).strip()
    )

    registry = AgentRegistry(config_path=config)
    content = registry.load_prompt("thesis")

    assert content is not None
    assert "SHARED FRAGMENT BODY" in content
    assert "{{include:" not in content
    assert "Pre-text." in content
    assert "Post-text." in content


def test_load_prompt_missing_include_raises(tmp_path):
    agents_dir = tmp_path / "prompts" / "agents"
    _write(
        agents_dir,
        "thesis.md",
        "{{include: _components/does_not_exist.md}}",
    )
    config = tmp_path / "agent_config.yaml"
    config.write_text(
        textwrap.dedent(
            """
            agents:
              thesis:
                prompt_path: prompts/agents/thesis.md
                model:
                  primary: claude-sonnet-4-20250514
                  fallback: claude-haiku-4-20250514
                output_schema: DocumentAngle
            """
        ).strip()
    )

    registry = AgentRegistry(config_path=config)
    with pytest.raises(FileNotFoundError, match="does_not_exist.md"):
        registry.load_prompt("thesis")


def test_load_prompt_resolves_multiple_includes(tmp_path):
    agents_dir = tmp_path / "prompts" / "agents"
    components_dir = agents_dir / "_components"
    _write(components_dir, "a.md", "AAA")
    _write(components_dir, "b.md", "BBB")
    _write(
        agents_dir,
        "thesis.md",
        "{{include: _components/a.md}}\n---\n{{include: _components/b.md}}",
    )
    config = tmp_path / "agent_config.yaml"
    config.write_text(
        textwrap.dedent(
            """
            agents:
              thesis:
                prompt_path: prompts/agents/thesis.md
                model:
                  primary: claude-sonnet-4-20250514
                  fallback: claude-haiku-4-20250514
                output_schema: DocumentAngle
            """
        ).strip()
    )

    registry = AgentRegistry(config_path=config)
    content = registry.load_prompt("thesis")
    assert "AAA" in content
    assert "BBB" in content


def test_real_components_resolve_from_thesis_prompt():
    """Once components and thesis.md are in place, load_prompt must succeed."""
    registry = AgentRegistry()
    content = registry.load_prompt("thesis")
    assert content is not None
    assert "{{include:" not in content
