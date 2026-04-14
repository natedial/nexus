"""Tests for round-based agent executor."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_analysis_layer.services.round_executor import (
    RoundExecutor,
    RoundConfig,
    AgentSpec,
)
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
)
from research_analysis_layer.models.agent_outputs import RoundTrace


class TestAgentExecutorRounds(unittest.TestCase):
    """Test round-based AgentExecutor functionality."""

    def test_round_executor_initialization(self):
        """RoundExecutor initializes with required components."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
            tool_registry=None,
        )

        self.assertIs(executor.registry, registry)
        self.assertIs(executor.llm_client, llm_client)
        self.assertIsNone(executor.tool_registry)

    def test_round_executor_with_tool_registry(self):
        """RoundExecutor accepts tool_registry."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()
        tool_registry = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
            tool_registry=tool_registry,
        )

        self.assertIs(executor.tool_registry, tool_registry)

    def test_run_sets_and_clears_shared_tool_budget(self):
        """RoundExecutor configures the shared tool budget for a run."""
        registry = MagicMock()
        registry.load_prompt.return_value = "Prompt"
        llm_client = MagicMock()
        llm_client.generate_with_tools.return_value = AgentCallResult(
            raw_text='{"document_key":"doc-1","research_id":1,"document_hash":"hash","analysis_version":"v1","thesis":"ok","contrarian_view":"counter","recommended_positioning":"hold","trading_opportunities":[],"short_time_horizon_insights":[],"talking_points":[],"cross_document_references":[],"confidence":0.8,"quality":{"score":0.9,"passed":true,"warnings":[]},"themes":[],"trades":[],"assertions":[],"world_nodes":[],"world_edges":[],"forecast_candidates":[]}',
            parsed_output={
                "document_key": "doc-1",
                "research_id": 1,
                "document_hash": "hash",
                "analysis_version": "v1",
                "thesis": "ok",
                "contrarian_view": "counter",
                "recommended_positioning": "hold",
                "trading_opportunities": [],
                "short_time_horizon_insights": [],
                "talking_points": [],
                "cross_document_references": [],
                "confidence": 0.8,
                "quality": {"score": 0.9, "passed": True, "warnings": []},
                "themes": [],
                "trades": [],
                "assertions": [],
                "world_nodes": [],
                "world_edges": [],
                "forecast_candidates": [],
            },
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="test-model",
            stop_reason="end_turn",
            attempt_count=1,
        )
        input_builder = MagicMock()
        input_builder.build.return_value = {"document": "payload"}
        input_builder.to_messages.return_value = [
            {"role": "user", "content": "payload"}
        ]
        tool_registry = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
            tool_registry=tool_registry,
        )
        document = MagicMock()
        document.research_id = 1
        document.document_hash = "hash"
        rounds = [
            RoundConfig(
                name="specialists",
                type="parallel",
                agents=["thesis"],
                receives=["input"],
            )
        ]
        agent_specs = {
            "thesis": AgentSpec(
                name="thesis",
                config=MagicMock(model="test-model"),
                tools=[],
                max_tool_calls=2,
                timeout_seconds=60,
                retry_count=1,
                temperature=0.4,
                output_schema="DocumentAngle",
            )
        }

        executor.run(
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            run_id=1,
            analysis_version="v1",
            rounds=rounds,
            agent_specs=agent_specs,
            max_total_tool_calls=3,
        )

        tool_registry.set_invocation_budget.assert_called_once_with(3)
        tool_registry.clear_invocation_budget.assert_called_once()

    def test_round_config_creation(self):
        """RoundConfig can be created with agent list."""
        config = RoundConfig(
            name="test_round",
            type="parallel",
            agents=["agent1", "agent2"],
            receives=["input"],
        )

        self.assertEqual(config.name, "test_round")
        self.assertEqual(config.type, "parallel")
        self.assertEqual(len(config.agents), 2)

    def test_agent_spec_creation(self):
        """AgentSpec captures agent configuration."""
        spec = AgentSpec(
            name="synthesizer",
            config=MagicMock(),
            tools=[],
            max_tool_calls=4,
            timeout_seconds=120,
            retry_count=3,
            temperature=0.4,
            output_schema="json",
        )

        self.assertEqual(spec.name, "synthesizer")
        self.assertEqual(spec.max_tool_calls, 4)
        self.assertEqual(spec.timeout_seconds, 120)

    def test_round_trace_creation(self):
        """RoundTrace captures round metrics."""
        trace = RoundTrace(
            round_name="test_round",
            duration_ms=1500,
            agent_count=2,
            failed_agent_count=0,
            tool_call_count=5,
            input_tokens=1000,
            output_tokens=500,
        )

        self.assertEqual(trace.round_name, "test_round")
        self.assertEqual(trace.duration_ms, 1500)
        self.assertEqual(trace.agent_count, 2)
        self.assertEqual(trace.tool_call_count, 5)

    def test_build_merged_input_includes_base(self):
        """_build_merged_input includes base input when receives contains 'input'."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()
        input_builder.build.return_value = {"text": "test input"}

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        document = MagicMock()
        result = executor._build_merged_input(
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            receives=["input"],
            prior_outputs={},
        )

        self.assertIn("base", result)
        input_builder.build.assert_called_once()

    def test_build_merged_input_skips_input_when_not_in_receives(self):
        """_build_merged_input excludes base when receives doesn't contain 'input'."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        document = MagicMock()
        result = executor._build_merged_input(
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            receives=["round1"],
            prior_outputs={"round1": []},
        )

        self.assertNotIn("base", result)

    def test_build_merged_input_includes_prior_round_output(self):
        """_build_merged_input includes prior round outputs."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()
        input_builder.build.return_value = {"text": "test input"}

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        document = MagicMock()
        prior_result = AgentCallResult(
            raw_text='{"angle": "thesis"}',
            parsed_output={"angle": "thesis", "summary": "summary", "confidence": 0.8},
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="test",
            stop_reason="end_turn",
            attempt_count=1,
        )

        result = executor._build_merged_input(
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            receives=["input", "round1"],
            prior_outputs={"round1": [prior_result]},
        )

        self.assertIn("base", result)
        self.assertIn("round1", result)
        self.assertEqual(len(result["round1"]), 1)


class TestRoundExecutorIntegration(unittest.TestCase):
    """Integration-style tests for RoundExecutor."""

    def test_document_analysis_returns_none_with_no_results(self):
        """_build_document_analysis returns None when no final results."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        document = MagicMock()
        document.research_id = 123
        document.document_hash = "abc123"

        result = executor._build_document_analysis(
            final_results=[],
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            run_id=1,
            analysis_version="v1",
            round_traces=[],
        )

        self.assertIsNone(result)

    def test_document_analysis_returns_none_with_no_parsed_output(self):
        """_build_document_analysis returns None when result has no parsed output."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        document = MagicMock()
        document.research_id = 123
        document.document_hash = "abc123"

        agent_result = AgentCallResult(
            raw_text="",
            parsed_output=None,
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="claude-3-5-sonnet",
            stop_reason="end_turn",
            attempt_count=1,
        )

        result = executor._build_document_analysis(
            final_results=[agent_result],
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            run_id=1,
            analysis_version="v1",
            round_traces=[],
        )

        self.assertIsNone(result)


class TestRoundExecutorEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_extract_angle_from_result_with_valid_output(self):
        """_extract_angle_from_result parses valid DocumentAngle."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        agent_result = AgentCallResult(
            raw_text='{"angle": "thesis", "summary": "Summary"}',
            parsed_output={
                "angle": "thesis",
                "summary": "Summary",
                "key_claims": [],
                "risks": [],
                "confidence": 0.8,
            },
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="test",
            stop_reason="end_turn",
            attempt_count=1,
        )

        angle = executor._extract_angle_from_result(agent_result)

        self.assertEqual(angle.angle, "thesis")
        self.assertEqual(angle.summary, "Summary")

    def test_extract_angle_from_result_with_no_output(self):
        """_extract_angle_from_result returns default for None output."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        agent_result = AgentCallResult(
            raw_text="",
            parsed_output=None,
            tool_calls=[],
            token_usage=TokenUsage(),
            model_used="test",
            stop_reason="end_turn",
            attempt_count=1,
        )

        angle = executor._extract_angle_from_result(agent_result)

        self.assertEqual(angle.angle, "thesis")
        self.assertEqual(angle.summary, "Specialist output unavailable")

    def test_create_error_result(self):
        """_create_error_result creates error AgentCallResult."""
        registry = MagicMock()
        llm_client = MagicMock()
        input_builder = MagicMock()

        executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=input_builder,
        )

        result = executor._create_error_result("Test error")

        self.assertIsNone(result.parsed_output)
        self.assertEqual(result.stop_reason, "error")
        self.assertEqual(result.tool_calls, [])


class TestRoundExecutorEndToEnd(unittest.TestCase):
    """End-to-end smoke tests wiring the full round pipeline together."""

    @staticmethod
    def _make_document(*, research_id: int, document_hash: str):
        from types import SimpleNamespace

        return SimpleNamespace(
            research_id=research_id,
            document_hash=document_hash,
            file_id=None,
            document=SimpleNamespace(
                document_name="doc.pdf",
                document_title="Test Doc",
                source="test",
                source_date="2026-04-14",
                publisher="test",
                area=None,
                region=None,
                asset_focus=None,
                document_link=None,
                trade_count=0,
                theme_count=0,
                parsed_data={},
            ),
            themes=[],
        )

    def test_round_executor_end_to_end_with_blank_identity_fields(self):
        """A synthesizer output with blank identity fields must still produce a
        valid DocumentAnalysis because the orchestrator stamps them."""
        from research_analysis_layer.services.agent_llm_client import (
            AgentCallResult,
            TokenUsage,
        )
        from research_analysis_layer.services.agent_registry import AgentRegistry
        from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
        from research_analysis_layer.services.round_executor import (
            AgentSpec,
            RoundExecutor,
        )

        def fake_generate_with_tools(**kwargs):
            system_prompt = kwargs.get("system_prompt", "")
            # Synthesizer returns blank identity fields — orchestrator must stamp them.
            if "Synthesizer Agent" in system_prompt:
                return AgentCallResult(
                    raw_text="",
                    parsed_output={
                        "document_key": "",
                        "research_id": 0,
                        "document_hash": "",
                        "analysis_version": "",
                        "thesis": "fused thesis",
                        "contrarian_view": "fused counter",
                        "recommended_positioning": "fused positioning",
                        "trading_opportunities": [],
                        "short_time_horizon_insights": [],
                        "talking_points": [],
                        "cross_document_references": [],
                        "confidence": 0.75,
                    },
                    tool_calls=[],
                    token_usage=TokenUsage(),
                    model_used="claude-sonnet-4-20250514",
                    stop_reason="end_turn",
                    attempt_count=1,
                )
            # Specialists return a minimal valid DocumentAngle.
            return AgentCallResult(
                raw_text="",
                parsed_output={
                    "angle": "thesis",
                    "summary": "a thesis",
                    "key_claims": [],
                    "cross_document_refs": [],
                    "risks": [],
                    "confidence": 0.8,
                },
                tool_calls=[],
                token_usage=TokenUsage(),
                model_used="claude-sonnet-4-20250514",
                stop_reason="end_turn",
                attempt_count=1,
            )

        class FakeClient:
            generate_with_tools = staticmethod(fake_generate_with_tools)

        registry = AgentRegistry()
        executor = RoundExecutor(
            registry=registry,
            llm_client=FakeClient(),
            input_builder=AgentInputBuilder(),
            tool_registry=None,
        )

        document = self._make_document(research_id=99, document_hash="hash-xyz")
        rounds = registry.get_rounds()
        agent_specs = {
            name: AgentSpec(
                name=name,
                config=registry.get_agent(name),
                tools=[],
                max_tool_calls=0,
                timeout_seconds=60,
                retry_count=1,
                temperature=0.4,
                output_schema="DocumentAngle",
            )
            for round_cfg in rounds
            for name in round_cfg.agents
        }

        analysis = executor.run(
            document=document,
            chunks=[],
            evidence_units=[],
            assertions=[],
            run_id=1,
            analysis_version="v2",
            rounds=rounds,
            agent_specs=agent_specs,
        )

        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.document_key, "doc:99:hash-xyz")
        self.assertEqual(analysis.research_id, 99)
        self.assertEqual(analysis.document_hash, "hash-xyz")
        self.assertEqual(analysis.analysis_version, "v2")
        self.assertEqual(analysis.thesis, "fused thesis")
        self.assertAlmostEqual(analysis.confidence, 0.75)
        self.assertEqual(analysis.quality, {})
        self.assertEqual(analysis.trades, [])
        self.assertEqual(analysis.assertions, [])


if __name__ == "__main__":
    unittest.main()
