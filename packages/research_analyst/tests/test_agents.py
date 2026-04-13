from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.config import Settings
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.main import command_list_agents
from research_analysis_layer.models import (
    AssertionDraft,
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedExcerpt,
    ParsedTheme,
)
from research_analysis_layer.services import AgentExecutor, AgentInputBuilder, Chunker, EvidenceBuilder
from research_analysis_layer.services.agent_registry import AgentRegistry


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
    def __init__(self, response: dict[str, object] | None = None, error: Exception | None = None):
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

    def test_agent_executor_persists_successful_result(self) -> None:
        document = make_document()
        chunks = Chunker().chunk_document(document)
        evidence_units = EvidenceBuilder().build_evidence(chunks, document)
        assertions = [
            AssertionDraft(
                chunk_order=1,
                assertion_order=1,
                assertion_type="forecast",
                text="Rates stay higher for longer because cuts are delayed.",
                normalized_text="rates stay higher for longer because cuts are delayed",
                summary_text="Higher for longer rates view",
                time_horizon="weeks",
            )
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "analysis.db"
            config_path = Path(tmpdir) / "agent_config.yaml"
            config_path.write_text(
                """
agents:
  trading_opportunities:
    prompt: prompts/trading_opportunities.md
    model: "claude-sonnet-4-20250514"
    fallback_model: "claude-sonnet-4-20250514"
    timeout_seconds: 30
    retry_count: 2
    priority: 1
    table_name: "trading_analysis"
                """.strip(),
                encoding="utf-8",
            )
            store = AnalysisStore(db_path)
            executor = AgentExecutor(
                store=store,
                registry=AgentRegistry(config_path=config_path),
                llm_client=StubLlmClient(
                    response={
                        "opportunities": [
                            {
                                "thesis": "Front-end yields stay elevated",
                                "direction": "short",
                                "instrument": "2Y Treasury",
                                "timeframe": "weeks",
                                "conviction": "medium",
                                "risk_reward_ratio": "1:2",
                                "key_levels": "entry 4.7 stop 4.5 target 5.1",
                                "rationale": "Cuts are being delayed by sticky inflation.",
                                "supporting_excerpts": ["Cuts are less likely in June."],
                                "risks": ["Soft data weakens materially"],
                            }
                        ],
                        "no_opportunity_reason": None,
                    }
                ),
                input_builder=AgentInputBuilder(),
            )

            summary = executor.execute(
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
                run_id=99,
                analysis_version="bootstrap-v1",
                selected_agents=["trading_opportunities"],
            )
            row = store.get_agent_result(
                table_name="trading_analysis",
                research_id=1,
                document_hash="hash123",
                analysis_version="bootstrap-v1",
            )

        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.error_count, 0)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["agent_type"], "trading_opportunities")
        opportunities = json.loads(row["opportunities_json"])
        self.assertEqual(opportunities[0]["instrument"], "2Y Treasury")

    def test_agent_executor_persists_error_result(self) -> None:
        document = make_document()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "analysis.db"
            config_path = Path(tmpdir) / "agent_config.yaml"
            config_path.write_text(
                """
agents:
  talking_points:
    prompt: prompts/talking_points.md
    model: "claude-haiku-4-20250514"
    fallback_model: "claude-haiku-4-20250514"
    timeout_seconds: 30
    retry_count: 2
    priority: 1
    table_name: "talking_points_analysis"
                """.strip(),
                encoding="utf-8",
            )
            store = AnalysisStore(db_path)
            executor = AgentExecutor(
                store=store,
                registry=AgentRegistry(config_path=config_path),
                llm_client=StubLlmClient(error=TimeoutError("timed out")),
                input_builder=AgentInputBuilder(),
            )

            summary = executor.execute(
                document=document,
                chunks=Chunker().chunk_document(document),
                evidence_units=[],
                assertions=[],
                run_id=101,
                analysis_version="bootstrap-v1",
                selected_agents=["talking_points"],
            )
            row = store.get_agent_result(
                table_name="talking_points_analysis",
                research_id=1,
                document_hash="hash123",
                analysis_version="bootstrap-v1",
            )

        self.assertEqual(summary.success_count, 0)
        self.assertEqual(summary.error_count, 1)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "error")
        self.assertIn("timed out", row["error_text"])

    def test_list_agents_command_outputs_registered_agents(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = command_list_agents(make_settings(Path("/tmp/test-analysis.db")))

        payload = json.loads(buffer.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(len(payload), 3)
        self.assertEqual(payload[0]["name"], "trading_opportunities")


if __name__ == "__main__":
    unittest.main()
