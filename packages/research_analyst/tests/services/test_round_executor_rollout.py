from unittest.mock import MagicMock
from research_analysis_layer.services.round_executor import (
    AgentSpec,
    RolloutStats,
    RoundConfig,
    RoundExecutor,
)


def test_rollout_stats_defaults_to_zero():
    stats = RolloutStats()
    assert stats.shadow_runs_total == 0
    assert stats.shadow_failures_total == 0
    assert stats.shadow_debate_truncated_total == 0
    assert stats.baseline_input_tokens == 0
    assert stats.debate_input_tokens == 0
    assert stats.baseline_duration_ms == 0
    assert stats.debate_duration_ms == 0


def test_round_executor_defaults_debate_mode_to_off():
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
    )
    assert ex.debate_mode == "off"
    assert isinstance(ex.rollout_stats, RolloutStats)


def test_round_executor_accepts_debate_mode_and_judge_override():
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="shadow",
        debate_judge_model="gpt-5-mini",
        max_debate_arguments=4,
    )
    assert ex.debate_mode == "shadow"
    assert ex.debate_judge_model == "gpt-5-mini"
    assert ex.max_debate_arguments == 4


def test_off_mode_skips_rounds_that_write_forum_state():
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.agent_llm_client import TokenUsage

    registry = MagicMock()
    input_builder = MagicMock()
    input_builder.build.return_value = {}
    input_builder.to_messages.return_value = []

    from research_analysis_layer.services.agent_llm_client import AgentCallResult

    llm = MagicMock()
    llm.generate_with_tools.return_value = AgentCallResult(
        raw_text="",
        parsed_output={
            "thesis": "t",
            "confidence": 0.5,
            "contrarian_view": "c",
            "recommended_positioning": "r",
        },
        tool_calls=[],
        token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        model_used="gpt-5-mini",
        stop_reason="end_turn",
        attempt_count=1,
    )

    ex = RoundExecutor(
        registry=registry,
        llm_client=llm,
        input_builder=input_builder,
        debate_mode="off",
    )
    rounds = [
        RoundConfig(
            name="proposal",
            type="parallel",
            agents=["proposer_thesis"],
            receives=["input"],
            writes_forum_state=True,
        ),
        RoundConfig(
            name="synthesis",
            type="sequential",
            agents=["synthesizer"],
            receives=["input"],
            output_schema="DocumentAnalysis",
            receives_forum_state=True,
        ),
    ]
    visited: list[str] = []
    original = ex._execute_sequential_round

    def spy(*, round_config, **kwargs):
        visited.append(round_config.name)
        return original(round_config=round_config, **kwargs)

    ex._execute_sequential_round = spy  # type: ignore[assignment]
    ex._execute_parallel_round = lambda **kw: (
        visited.append(kw["round_config"].name),  # type: ignore[assignment]
        _fake_result(kw["round_config"].name),
    )[1]

    agent_specs = {
        "synthesizer": AgentSpec(
            name="synthesizer",
            config=AgentConfig(
                name="synthesizer",
                prompt_path="prompts/synthesizer.md",
                model="gpt-5-mini",
                fallback_model="gpt-5-mini",
                timeout_seconds=60,
                retry_count=1,
                priority=90,
                table_name="synthesizer",
                output_schema="DocumentAnalysis",
                tools=[],
                max_tool_calls=0,
                temperature=0.2,
            ),
            tools=[],
            max_tool_calls=0,
            timeout_seconds=60,
            retry_count=1,
            temperature=0.2,
            output_schema="DocumentAnalysis",
        ),
    }

    document = MagicMock(research_id=1, document_hash="h", file_id=None)
    document.document = None
    document.themes = []
    ex.run(
        document=document,
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=1,
        analysis_version="v1",
        rounds=rounds,
        agent_specs=agent_specs,
    )
    assert "proposal" not in visited
    assert "synthesis" in visited


def _fake_result(name: str):
    from research_analysis_layer.services.round_executor import RoundResult

    return RoundResult(
        round_name=name,
        agent_results=[],
        duration_ms=0,
        failed_count=0,
        tool_call_count=0,
    )


def test_run_baseline_synthesis_skips_forum_state_and_returns_analysis(monkeypatch):
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.agent_llm_client import (
        AgentCallResult,
        TokenUsage,
    )
    from research_analysis_layer.services.round_executor import AgentSpec, RoundConfig

    registry = MagicMock()
    registry.load_prompt.return_value = "system"
    input_builder = MagicMock()
    input_builder.build.return_value = {"base": {"document": {"research_id": 7}}}
    input_builder.to_messages.return_value = [{"role": "user", "content": "x"}]

    llm = MagicMock()
    llm.generate_with_tools.return_value = AgentCallResult(
        raw_text="",
        parsed_output={
            "thesis": "baseline-thesis",
            "confidence": 0.7,
            "contrarian_view": "cv",
            "recommended_positioning": "rp",
        },
        tool_calls=[],
        token_usage=TokenUsage(input_tokens=10, output_tokens=5),
        model_used="gpt-5-mini",
        stop_reason="end_turn",
        attempt_count=1,
    )

    ex = RoundExecutor(
        registry=registry,
        llm_client=llm,
        input_builder=input_builder,
        debate_mode="shadow",
    )

    synth_round = RoundConfig(
        name="synthesis",
        type="sequential",
        agents=["synthesizer"],
        receives=["input"],
        output_schema="DocumentAnalysis",
        receives_forum_state=True,
    )
    spec = AgentSpec(
        name="synthesizer",
        config=AgentConfig(
            name="synthesizer",
            prompt_path="",
            model="gpt-5-mini",
            output_schema="DocumentAnalysis",
            tools=[],
            max_tool_calls=0,
            timeout_seconds=60,
            retry_count=1,
            temperature=0.2,
            priority=90,
            fallback_model="gpt-5-mini",
            table_name="synthesizer",
        ),
        tools=[],
        max_tool_calls=0,
        timeout_seconds=60,
        retry_count=1,
        temperature=0.2,
        output_schema="DocumentAnalysis",
    )
    document = MagicMock(research_id=7, document_hash="abc", file_id=None)
    document.document = None
    document.themes = []

    analysis = ex.run_baseline_synthesis(
        document=document,
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=1,
        analysis_version="v1",
        synth_round=synth_round,
        synth_spec=spec,
    )

    assert analysis is not None
    assert analysis.thesis == "baseline-thesis"
    last_messages_call = input_builder.to_messages.call_args_list[-1].args[0]
    assert "forum_context" not in last_messages_call
    assert ex.rollout_stats.baseline_input_tokens == 10
    assert ex.rollout_stats.baseline_output_tokens == 5
    assert ex.rollout_stats.baseline_duration_ms >= 0


def test_forum_context_trimmed_to_max_debate_arguments():
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="on",
        max_debate_arguments=2,
    )
    forum_context = {
        "arguments": [
            {"argument_id": "a1"},
            {"argument_id": "a2"},
            {"argument_id": "a3"},
            {"argument_id": "a4"},
        ],
        "relations": [],
    }
    trimmed, truncated = ex._apply_argument_cap(forum_context)
    assert len(trimmed["arguments"]) == 2
    assert truncated is True


def test_forum_context_under_cap_not_truncated():
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="on",
        max_debate_arguments=8,
    )
    ctx = {"arguments": [{"argument_id": "a1"}], "relations": []}
    trimmed, truncated = ex._apply_argument_cap(ctx)
    assert len(trimmed["arguments"]) == 1
    assert truncated is False


def test_shadow_truncation_counted_once_per_session():
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="shadow",
        max_debate_arguments=1,
    )
    ex._note_truncation(session_truncated_flag={"v": False})
    ex._note_truncation(session_truncated_flag={"v": True})
    assert ex.rollout_stats.shadow_debate_truncated_total == 1


def test_debate_judge_model_overrides_adjudicator_spec():
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.round_executor import AgentSpec

    spec = AgentSpec(
        name="adjudicator",
        config=AgentConfig(
            name="adjudicator",
            prompt_path="",
            model="gpt-5-mini",
            output_schema="DebateRoundOutput",
            tools=[],
            max_tool_calls=0,
            timeout_seconds=60,
            retry_count=1,
            temperature=0.2,
            priority=80,
            fallback_model="gpt-5-mini",
            table_name="adjudicator",
        ),
        tools=[],
        max_tool_calls=0,
        timeout_seconds=60,
        retry_count=1,
        temperature=0.2,
        output_schema="DebateRoundOutput",
    )
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="on",
        debate_judge_model="override-judge",
    )
    patched = ex._apply_judge_model_override({"adjudicator": spec})
    assert patched["adjudicator"].config.model == "override-judge"


def test_debate_judge_model_none_leaves_spec_unchanged():
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.round_executor import AgentSpec

    spec = AgentSpec(
        name="adjudicator",
        config=AgentConfig(
            name="adjudicator",
            prompt_path="",
            model="gpt-5-mini",
            output_schema="DebateRoundOutput",
            tools=[],
            max_tool_calls=0,
            timeout_seconds=60,
            retry_count=1,
            temperature=0.2,
            priority=80,
            fallback_model="gpt-5-mini",
            table_name="adjudicator",
        ),
        tools=[],
        max_tool_calls=0,
        timeout_seconds=60,
        retry_count=1,
        temperature=0.2,
        output_schema="DebateRoundOutput",
    )
    ex = RoundExecutor(
        registry=MagicMock(),
        llm_client=MagicMock(),
        input_builder=MagicMock(),
        debate_mode="on",
        debate_judge_model=None,
    )
    patched = ex._apply_judge_model_override({"adjudicator": spec})
    assert patched["adjudicator"].config.model == "gpt-5-mini"
