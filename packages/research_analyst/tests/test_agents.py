from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.main import command_list_agents
from research_analysis_layer.models import (
    AssertionDraft,
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
    render_payload_structure_markdown,
)
from research_analysis_layer.services import (
    AgentInputBuilder,
    Chunker,
    EvidenceBuilder,
)


def make_settings(db_path: Path) -> Settings:
    return Settings(
        analysis_db_url=f"sqlite:///{db_path}",
        parsed_db_url="https://example.supabase.co",
        parsed_db_key="secret",
        calendar_db_url="https://calendar.example.supabase.co",
        calendar_db_key="calendar-secret",
        calendar_match_source="economic_events",
        calendar_source_name="economic_events",
        state_db_path=Path("data/state.db"),
        batch_size=25,
        cron_mode_enabled=True,
        analysis_version="bootstrap-v1",
        chunker_version="deterministic-theme-v1",
        assertion_extractor_version="deterministic-theme-v1",
        resolver_version="bootstrap-v1",
        request_timeout_seconds=30,
        min_full_text_chars=500,
        min_quality_score=0.6,
        min_usable_theme_ratio=0.6,
        backfill_require_warning_free=True,
    )


def make_document() -> HydratedParsedDocument:
    parsed_data = {
        "full_text": "Macro outlook " * 200,
        "metadata": {"document_id": "file-1", "publisher_slug": "jpm"},
    }
    document = ParsedDocument(
        id=1,
        document_name="2026-03-30_JPM_macro_outlook.pdf",
        source="J.P. Morgan",
        source_date="2026-03-30",
        parsed_data=parsed_data,
        theme_count=2,
        trade_count=1,
        document_hash="hash123",
    )
    themes = [
        ParsedTheme(
            id=10,
            research_id=1,
            theme_order=1,
            label="Delayed cuts",
            scope=None,
            primary_category="Rates",
            relevance=["Rates"],
            classification="Forecast",
            strength="Primary",
            confidence="High",
            evidence_count=2,
            mention_count=1,
            context="Cuts are less likely in June." * 40,
            directionality=None,
            argument_structure=None,
        ),
        ParsedTheme(
            id=11,
            research_id=1,
            theme_order=2,
            label="Higher term premium",
            scope=None,
            primary_category="Macro",
            relevance=["Macro"],
            classification="Description",
            strength="Primary",
            confidence="High",
            evidence_count=2,
            mention_count=1,
            context="Supply pressure keeps term premium elevated.",
            directionality=None,
            argument_structure=None,
        ),
    ]
    excerpts = [
        [ParsedExcerpt(id=101, theme_id=10, excerpt_order=1, excerpt_text="A" * 900)],
        [ParsedExcerpt(id=102, theme_id=11, excerpt_order=1, excerpt_text="B" * 140)],
    ]
    hydrated_themes = [
        HydratedTheme(theme=theme, excerpts=theme_excerpts)
        for theme, theme_excerpts in zip(themes, excerpts)
    ]
    return HydratedParsedDocument(
        document=document,
        themes=hydrated_themes,
        file_id="file-1",
    )


class StubLlmClient:
    def __init__(
        self, response: dict[str, object] | None = None, error: Exception | None = None
    ):
        self.response = response or {}
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        model: str,
        timeout_seconds: int,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "model": model,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return dict(self.response)


class AgentsTest(unittest.TestCase):
    def test_agent_input_builder_truncates_payload(self) -> None:
        document = make_document()
        builder = AgentInputBuilder(
            max_full_text_chars=200,
            max_theme_context_chars=120,
            max_excerpt_chars=100,
        )
        payload = builder.build(
            agent_type="trading_opportunities",
            document=document,
            chunks=Chunker().chunk_document(document),
            evidence_units=EvidenceBuilder().build_evidence(
                Chunker().chunk_document(document),
                document,
            ),
            assertions=[
                AssertionDraft(
                    chunk_order=1,
                    assertion_order=1,
                    assertion_type="forecast",
                    text="Rates stay higher for longer because cuts are delayed.",
                    normalized_text="rates stay higher for longer because cuts are delayed",
                    summary_text="Higher for longer rates view",
                    time_horizon="weeks",
                )
            ],
        )

        self.assertLessEqual(len(payload["document"]["full_text_excerpt"]), 200)
        self.assertLessEqual(len(payload["themes"][0]["context"]), 120)
        self.assertLessEqual(len(payload["themes"][0]["excerpts"][0]), 100)
        self.assertEqual(payload["document"]["metadata"]["publisher_slug"], "jpm")

    def test_list_agents_command_outputs_registered_agents(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = command_list_agents(
                make_settings(Path("/tmp/test-analysis.db"))
            )

        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(len(payload), 3)
        self.assertEqual(payload[0]["name"], "thesis")


def test_synthesizer_prompt_mentions_key_contract_points():
    """The synthesizer prompt must document the real input shape and the
    output sub-schemas, and must clearly mark orchestrator-overridden fields."""
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    content = registry.load_prompt("synthesizer")
    assert content is not None

    # It describes the specialist input shape correctly.
    assert "DocumentAngle" in content or "specialists" in content.lower()

    # It documents the sub-schemas for structured outputs.
    assert "TradingOpportunity" in content
    assert "TalkingPoint" in content
    assert "ShortTimeHorizonInsight" in content

    # It tells the model the orchestrator will override identity fields.
    assert "document_key" in content
    assert "orchestrator" in content.lower()

    # It tells the model to merge specialist cross_document_refs.
    assert "cross_document_ref" in content
    assert "merge" in content.lower() or "union" in content.lower()

    # It does not reference the old misleading phrase.
    assert "evidence pack" not in content.lower()


def test_payload_structure_component_matches_runtime_schema():
    component_path = (
        Path(__file__).resolve().parents[1]
        / "prompts/agents/_components/payload_structure.md"
    )
    assert component_path.read_text().strip() == render_payload_structure_markdown()


def test_thesis_prompt_uses_shared_components():
    """The thesis prompt must pull in payload_structure, research_search_guide,
    and confidence_rubric, and must point at deterministic_analysis.assertions."""
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    content = registry.load_prompt("thesis")
    assert content is not None

    # Includes were resolved (fragment content present, directive absent).
    assert "{{include:" not in content
    assert "Confidence calibration" in content  # from confidence_rubric.md
    assert "deterministic_analysis" in content   # from payload_structure.md
    assert "research_search" in content          # from research_search_guide.md

    # Core instruction is preserved.
    assert "thesis" in content.lower()
    assert "DocumentAngle" in content or '"angle": "thesis"' in content


def test_contrarian_prompt_uses_shared_components_and_search_strategy():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    content = registry.load_prompt("contrarian")
    assert content is not None

    assert "{{include:" not in content
    assert "Confidence calibration" in content
    assert "deterministic_analysis" in content
    assert "research_search" in content

    # Contrarian-specific: explicit tool budget guidance.
    assert "6" in content  # 6 tool calls budget from agent_config.yaml
    assert '"angle": "contrarian"' in content or "angle=\"contrarian\"" in content


def test_positioning_prompt_uses_assertions_and_has_no_tools():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    content = registry.load_prompt("positioning")
    assert content is not None

    assert "{{include:" not in content
    assert "Confidence calibration" in content
    assert "deterministic_analysis" in content
    # Positioning has no tools — the prompt must say so.
    assert "no tools" in content.lower() or "no research_search" in content.lower()
    # It must specifically direct the agent at polarity / time_horizon.
    assert "polarity" in content
    assert "time_horizon" in content


def test_thesis_config_tools_match_prompt_documentation():
    """Every tool granted to thesis must be documented in its prompt."""
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    thesis_cfg = registry.get_agent("thesis")
    assert thesis_cfg is not None

    prompt = registry.load_prompt("thesis")
    assert prompt is not None

    for tool in thesis_cfg.tools or []:
        assert tool in prompt, (
            f"thesis config grants tool {tool!r} but the prompt does not "
            f"document when/how to use it — either document it or remove "
            f"it from agent_config.yaml"
        )


if __name__ == "__main__":
    unittest.main()
