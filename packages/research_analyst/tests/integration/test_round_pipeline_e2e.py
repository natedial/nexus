"""Focused integration tests for the round-based pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from research_analysis_layer.models.agent_outputs import DocumentAnalysis
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.agent_llm_client import (
    AgentCallResult,
    TokenUsage,
    ToolCallTrace,
)
from research_analysis_layer.services.agent_registry import AgentConfig
from research_analysis_layer.services.round_executor import (
    AgentSpec,
    RoundConfig,
    RoundExecutor,
)


class _Document:
    def __init__(self) -> None:
        self.research_id = 1
        self.document_hash = "abc123def456"
        self.file_id = "file_001"
        self.document = MagicMock()
        self.document.parsed_data = {
            "metadata": {"source": "test"},
            "document_title": "Test Document",
        }
        self.themes = []
        self.ready_for_analysis = True


class _StubInputBuilder(AgentInputBuilder):
    def build(self, **kwargs):  # type: ignore[override]
        return {
            "document": {"title": "Test", "content": "Test content"},
            "chunks": [],
            "assertions": [],
        }

    def to_messages(self, input_data):  # type: ignore[override]
        return [{"role": "user", "content": "Analyze this document"}]


def _make_agent_spec(*, tools: list[dict] | None = None) -> AgentSpec:
    agent_cfg = AgentConfig(
        name="synthesizer",
        prompt_path="prompts/agents/synthesizer.txt",
        model="claude-sonnet-4-20250514",
        fallback_model="",
        temperature=0.0,
        max_tool_calls=4,
        timeout_seconds=120,
        retry_count=1,
        priority=1,
        table_name="agent_outputs",
        tools=["research_search"] if tools else [],
        output_schema="DocumentAnalysis",
    )
    return AgentSpec(
        name="synthesizer",
        config=agent_cfg,
        tools=tools or [],
        max_tool_calls=4,
        timeout_seconds=120,
        retry_count=1,
        temperature=0.0,
        output_schema="DocumentAnalysis",
    )


def _make_result(*, tool_calls: list[ToolCallTrace] | None = None) -> AgentCallResult:
    return AgentCallResult(
        raw_text='{"thesis":"Test thesis","contrarian_view":"Test contrarian","recommended_positioning":"Test positioning","trading_opportunities":[],"short_time_horizon_insights":[],"talking_points":[],"cross_document_references":[],"quality":{},"themes":[],"trades":[],"assertions":[],"world_nodes":[],"world_edges":[],"forecast_candidates":[],"confidence":0.8}',
        parsed_output={
            "thesis": "Test thesis",
            "contrarian_view": "Test contrarian",
            "recommended_positioning": "Test positioning",
            "trading_opportunities": [],
            "short_time_horizon_insights": [],
            "talking_points": [],
            "cross_document_references": [],
            "quality": {},
            "themes": [],
            "trades": [],
            "assertions": [],
            "world_nodes": [],
            "world_edges": [],
            "forecast_candidates": [],
            "confidence": 0.8,
        },
        tool_calls=tool_calls or [],
        token_usage=TokenUsage(
            input_tokens=500,
            output_tokens=300,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=50,
        ),
        model_used="claude-sonnet-4-20250514",
        stop_reason="end_turn",
        attempt_count=1,
        agent_name="synthesizer",
    )


@pytest.mark.integration
def test_round_executor_returns_document_analysis_on_valid_output():
    registry = MagicMock()
    registry.load_prompt.return_value = "You are a synthesizer agent."
    llm_client = MagicMock()
    llm_client.generate_with_tools.return_value = _make_result()

    executor = RoundExecutor(
        registry=registry,
        llm_client=llm_client,
        input_builder=_StubInputBuilder(),
        tool_registry=MagicMock(),
    )

    result = executor.run(
        document=_Document(),
        chunks=[MagicMock(chunk_order=0, content="chunk")],
        evidence_units=[],
        assertions=[MagicMock(claim="assertion")],
        run_id=42,
        analysis_version="2026-04-16",
        rounds=[
            RoundConfig(
                name="synthesis",
                type="parallel",
                agents=["synthesizer"],
                receives=["input"],
                output_schema="DocumentAnalysis",
            )
        ],
        agent_specs={"synthesizer": _make_agent_spec()},
    )

    assert isinstance(result, DocumentAnalysis)
    assert result.document_key == "file:file_001"
    assert result.research_id == 1
    assert result.document_hash == "abc123def456"
    assert result.analysis_version == "2026-04-16"
    assert result.thesis == "Test thesis"
    assert len(result.round_traces) == 1


@pytest.mark.integration
def test_round_executor_records_tool_call_metrics_in_round_trace():
    registry = MagicMock()
    registry.load_prompt.return_value = "You are a synthesizer agent."
    llm_client = MagicMock()
    llm_client.generate_with_tools.return_value = _make_result(
        tool_calls=[
            ToolCallTrace(
                name="research_search",
                input={"query": "fed"},
                output_summary="Found 2 results",
                duration_ms=120,
                is_error=False,
            )
        ]
    )

    tool_registry = MagicMock()
    tool_registry.set_invocation_budget = MagicMock()
    tool_registry.clear_invocation_budget = MagicMock()
    tool_schema = {
        "name": "research_search",
        "description": "Search research corpus",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    tool_registry.get_schema.return_value = tool_schema

    executor = RoundExecutor(
        registry=registry,
        llm_client=llm_client,
        input_builder=_StubInputBuilder(),
        tool_registry=tool_registry,
    )

    result = executor.run(
        document=_Document(),
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=7,
        analysis_version="v1",
        rounds=[
            RoundConfig(
                name="synthesis",
                type="parallel",
                agents=["synthesizer"],
                receives=["input"],
                output_schema="DocumentAnalysis",
            )
        ],
        agent_specs={"synthesizer": _make_agent_spec(tools=[tool_schema])},
        max_total_tool_calls=2,
    )

    assert result is not None
    assert len(result.round_traces) == 1
    round_trace = result.round_traces[0]
    assert round_trace.tool_call_count == 1
    assert round_trace.input_tokens == 500
    assert round_trace.output_tokens == 300
    assert round_trace.cache_read_input_tokens == 100
    assert round_trace.cache_creation_input_tokens == 50
    tool_registry.set_invocation_budget.assert_called_once_with(2)
    tool_registry.clear_invocation_budget.assert_called_once()
