from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
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
        names = {item["name"] for item in payload}
        self.assertIn("proposer_thesis", names)
        self.assertIn("challenger", names)
        self.assertIn("synthesizer", names)
        synthesizer = next(item for item in payload if item["name"] == "synthesizer")
        self.assertEqual(synthesizer["output_schema"], "DocumentAnalysis")

    def test_agent_input_builder_serializes_datetime_payloads(self) -> None:
        builder = AgentInputBuilder()
        messages = builder.to_messages(
            {
                "base": {"document": {"title": "Example"}},
                "forum_context": {
                    "arguments": [
                        {
                            "argument_id": "arg-1",
                            "created_at": datetime(
                                2026, 4, 15, 12, 0, tzinfo=timezone.utc
                            ),
                        }
                    ]
                },
            }
        )

        forum_payload = json.loads(messages[1]["content"][0]["text"])
        self.assertEqual(
            forum_payload["arguments"][0]["created_at"],
            "2026-04-15T12:00:00+00:00",
        )


def test_synthesizer_prompt_mentions_key_contract_points():
    """The synthesizer uses forum state when present, otherwise the base payload."""
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    content = registry.load_prompt("synthesizer")
    assert content is not None

    assert "forum_context" in content
    assert "accepted/synthesized" in content
    assert "verdict" in content.lower()
    assert "debate rounds were skipped" in content

    # It documents the sub-schemas for structured outputs.
    assert "TradingOpportunity" in content
    assert "TalkingPoint" in content
    assert "ShortTimeHorizonInsight" in content

    # It tells the model the orchestrator will override identity fields.
    assert "document_key" in content
    assert "orchestrator" in content.lower()

    assert "Do not refuse" in content


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
    assert "argument_graph" in content
    assert "publisher" in content.lower()


def test_contrarian_and_challenger_config_tools_match_prompt_documentation():
    """Tools granted to the pressure-test agents must be documented in-prompt."""
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    for agent_name in ("contrarian", "challenger"):
        cfg = registry.get_agent(agent_name)
        assert cfg is not None
        prompt = registry.load_prompt(agent_name)
        assert prompt is not None
        assert "argument_graph" in (cfg.tools or [])
        assert "research_search" in (cfg.tools or [])
        for tool in cfg.tools or []:
            assert tool in prompt, (
                f"{agent_name} config grants tool {tool!r} but the prompt does "
                f"not document when/how to use it"
            )


def test_thesis_does_not_get_argument_graph_tool():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    thesis = registry.get_agent("thesis")
    synthesizer = registry.get_agent("synthesizer")
    assert thesis is not None
    assert "argument_graph" not in (thesis.tools or [])
    assert synthesizer is not None
    assert synthesizer.tools == []


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


def test_debate_round_config_loads_expected_rounds():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    rounds = registry.get_rounds()

    assert [round_config.name for round_config in rounds] == [
        "proposal",
        "challenge",
        "rebuttal",
        "adjudication",
        "synthesis",
    ]
    assert rounds[0].writes_forum_state is True
    assert rounds[1].receives_forum_state is True
    assert rounds[-1].target_selector == "accepted_only"


def test_debate_prompts_load_with_includes_resolved():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()

    for agent_name in (
        "proposer_thesis",
        "challenger",
        "rebuttal",
        "adjudicator",
    ):
        content = registry.load_prompt(agent_name)
        assert content is not None
        assert "{{include:" not in content


def test_synthesizer_prompt_includes_argument_map_schema():
    from research_analysis_layer.services.agent_registry import AgentRegistry
    content = AgentRegistry().load_prompt("synthesizer")
    assert content is not None
    assert "{{include:" not in content            # include resolved
    assert "argument_map" in content
    assert "rationale" in content and "support_strength" in content
    assert "evidenced" in content and "asserted" in content


def test_legacy_synthesizer_prompt_includes_argument_map_schema():
    """The unused-by-default synthesizer.md must emit the same map contract."""
    from pathlib import Path
    from research_analysis_layer.services.agent_registry import AgentRegistry

    text = Path("prompts/agents/synthesizer.md").read_text()
    assert "{{include: _components/argument_map.md}}" in text
    assert "argument_map" in text
    assert "3 and 7" in text or "3–7" in text or "3-7" in text

    # Resolve includes the same way the registry does, from that file's directory.
    registry = AgentRegistry()
    resolved = registry._INCLUDE_PATTERN.sub(
        lambda m: (
            (Path("prompts/agents") / m.group("path").strip()).read_text().rstrip()
        ),
        text,
    )
    assert "{{include:" not in resolved
    assert "rationale" in resolved and "support_strength" in resolved
    assert "evidenced" in resolved and "asserted" in resolved
    assert "referent_key" in resolved and "claim_key" in resolved


def test_synthesizer_prompt_ports_argumentation_rubric():
    """Live synthesizer.md gets the rubric include and the reconciled terminology."""
    from pathlib import Path
    from research_analysis_layer.services.agent_registry import AgentRegistry

    text = Path("prompts/agents/synthesizer.md").read_text()
    assert "{{include: _components/argumentation_rubric.md}}" in text
    assert "## Lenses vs. publishers" in text
    assert "### Mapping the rubric to output fields" in text
    assert "If two specialists disagree" not in text
    assert "{{include: _components/payload_structure.md}}" in text  # refit includes kept

    resolved = AgentRegistry._INCLUDE_PATTERN.sub(
        lambda m: (
            (Path("prompts/agents") / m.group("path").strip()).read_text().rstrip()
        ),
        text,
    )
    assert "{{include:" not in resolved
    assert "Positions belong to publishers" in resolved
    assert "analytical tension" in resolved
    assert "consensus across publishers" in resolved


def test_thesis_and_contrarian_prompts_include_argumentation_rubric():
    from research_analysis_layer.services.agent_registry import AgentRegistry

    registry = AgentRegistry()
    for agent_name in ("thesis", "contrarian"):
        content = registry.load_prompt(agent_name)
        assert content is not None
        assert "{{include:" not in content
        assert "Positions belong to publishers" in content
        assert "analytical tension" in content

    contrarian = registry.load_prompt("contrarian")
    assert "rival" in contrarian.lower() or "publisher" in contrarian.lower()


def test_claim_node_defaults_and_evidenced_downgrade():
    from research_analysis_layer.models.agent_outputs import ClaimNode, EvidenceRef

    # A bare claim is valid and defaults to 'asserted'.
    bare = ClaimNode(claim="the Fed is done hiking")
    assert bare.support_strength == "asserted"
    assert bare.evidence == [] and bare.conditions == []

    # 'evidenced' without a grounded ref_key is honestly downgraded to 'reasoned'.
    ungrounded = ClaimNode(
        claim="first cut in Q2",
        rationale="dot median implies an earlier move",
        support_strength="evidenced",
        evidence=[EvidenceRef(text="the dots look dovish", ref_key=None)],
    )
    assert ungrounded.support_strength == "reasoned"

    # 'evidenced' with a real ref_key is preserved.
    grounded = ClaimNode(
        claim="services inflation is cooling",
        support_strength="evidenced",
        evidence=[EvidenceRef(text="3m saar decelerating", ref_key="assertion:chunk-5:0")],
    )
    assert grounded.support_strength == "evidenced"
    # Both resolved-identity slots exist now and stay null until the Slice 2 resolver runs.
    assert grounded.evidence[0].referent_key is None
    assert grounded.claim_key is None
    assert bare.horizon is None


def test_argument_map_meta_defaults():
    from research_analysis_layer.models.agent_outputs import ArgumentMapMeta, ARGUMENT_MAP_VERSION
    meta = ArgumentMapMeta(extractor_version=ARGUMENT_MAP_VERSION)
    assert meta.run_id is None and meta.captured_at is None  # orchestrator stamps these


def test_document_analysis_argument_map_is_additive_and_defaults_empty():
    from research_analysis_layer.models.agent_outputs import (
        AgentExecutionMetadata,
        DocumentAnalysis,
    )

    da = DocumentAnalysis(
        document_key="doc:1:h",
        research_id=1,
        document_hash="h",
        analysis_version="argmap-v1",
        thesis="t",
        contrarian_view="c",
        recommended_positioning="p",
        confidence=0.5,
        metadata=AgentExecutionMetadata(
            research_id=1,
            document_hash="h",
            analysis_version="argmap-v1",
            agent_type="synthesizer",
            model_requested="m",
            model_used="m",
            prompt_path="p",
            prompt_version="v",
            run_id=1,
            attempt_count=1,
        ),
    )
    assert da.argument_map == []          # existing callers unaffected
    assert da.argument_map_meta is None   # stamped by the orchestrator when a map is built


if __name__ == "__main__":
    unittest.main()
