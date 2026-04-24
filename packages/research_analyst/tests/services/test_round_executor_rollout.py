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


def test_argument_cap_applied_in_run_and_truncation_counted(monkeypatch):
    """When run() receives forum_context with more args than max, cap is enforced."""
    from research_analysis_layer.models.debate_models import (
        DebateArgument,
        DebateSession,
        ForumContext,
        ThesisType,
    )
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.agent_llm_client import (
        AgentCallResult,
        TokenUsage,
    )
    from datetime import datetime, timezone

    big_context = ForumContext(
        research_id=1,
        document_hash="abc",
        analysis_version="v1",
        run_id=1,
        arguments=[
            DebateArgument(
                argument_id=f"arg{i}",
                session_id="test-session",
                turn_name=f"turn{i}",
                agent_name="proposer",
                thesis_type=ThesisType.THESIS,
                argument_text=f"arg {i}",
                confidence=0.5,
            )
            for i in range(3)
        ],
        relations=[],
    )

    session_builder = MagicMock()
    session_builder.build_round_context.return_value = big_context

    captured_forum_contexts: list = []
    original_build = RoundExecutor._build_merged_input

    def spy_build(self_inner, *, forum_context=None, **kwargs):
        captured_forum_contexts.append(forum_context)
        return original_build(self_inner, forum_context=forum_context, **kwargs)

    monkeypatch.setattr(RoundExecutor, "_build_merged_input", spy_build)

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
        token_usage=TokenUsage(input_tokens=5, output_tokens=2),
        model_used="gpt-5-mini",
        stop_reason="end_turn",
        attempt_count=1,
    )

    input_builder = MagicMock()
    input_builder.build.return_value = {}
    input_builder.to_messages.return_value = []

    registry = MagicMock()
    registry.load_prompt.return_value = "system"

    ex = RoundExecutor(
        registry=registry,
        llm_client=llm,
        input_builder=input_builder,
        session_builder=session_builder,
        debate_mode="shadow",
        max_debate_arguments=2,
    )

    fake_session = MagicMock(spec=DebateSession)
    monkeypatch.setattr(ex, "_initialize_debate_session", lambda **_: fake_session)
    monkeypatch.setattr(ex, "_persist_debate_round_outputs", lambda **kw: kw["session"])

    synth_round = RoundConfig(
        name="synthesis",
        type="sequential",
        agents=["synthesizer"],
        receives=["input"],
        output_schema="DocumentAnalysis",
        receives_forum_state=True,
        writes_forum_state=False,
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

    document = MagicMock(research_id=1, document_hash="abc", file_id=None)
    document.document = None
    document.themes = []

    ex.run(
        document=document,
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=1,
        analysis_version="v1",
        rounds=[synth_round],
        agent_specs={"synthesizer": spec},
    )

    forum_ctx_used = next(fc for fc in captured_forum_contexts if fc is not None)
    assert len(forum_ctx_used["arguments"]) == 2
    assert ex.rollout_stats.shadow_debate_truncated_total == 1


def test_debate_token_counters_populated_after_run(monkeypatch):
    """Tokens from debate rounds (writes_forum_state=True) accumulate in rollout_stats."""
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.agent_llm_client import (
        AgentCallResult,
        TokenUsage,
    )
    from research_analysis_layer.models.debate_models import DebateSession

    registry = MagicMock()
    registry.load_prompt.return_value = "system"
    input_builder = MagicMock()
    input_builder.build.return_value = {}
    input_builder.to_messages.return_value = []

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
        token_usage=TokenUsage(input_tokens=20, output_tokens=10),
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

    debate_round = RoundConfig(
        name="proposal",
        type="sequential",
        agents=["proposer"],
        receives=["input"],
        writes_forum_state=True,
        receives_forum_state=False,
    )
    synth_round = RoundConfig(
        name="synthesis",
        type="sequential",
        agents=["synthesizer"],
        receives=["input"],
        output_schema="DocumentAnalysis",
        writes_forum_state=False,
        receives_forum_state=False,
    )

    proposer_spec = AgentSpec(
        name="proposer",
        config=AgentConfig(
            name="proposer",
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
            table_name="proposer",
        ),
        tools=[],
        max_tool_calls=0,
        timeout_seconds=60,
        retry_count=1,
        temperature=0.2,
        output_schema="DebateRoundOutput",
    )
    synth_spec = AgentSpec(
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

    monkeypatch.setattr(ex, "_initialize_debate_session", lambda **_: None)

    document = MagicMock(research_id=1, document_hash="abc", file_id=None)
    document.document = None
    document.themes = []

    ex.run(
        document=document,
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=1,
        analysis_version="v1",
        rounds=[debate_round, synth_round],
        agent_specs={"proposer": proposer_spec, "synthesizer": synth_spec},
    )

    assert ex.rollout_stats.debate_input_tokens == 20
    assert ex.rollout_stats.debate_output_tokens == 10
    assert ex.rollout_stats.debate_duration_ms >= 0


def test_last_synthesizer_input_stored_after_run(monkeypatch):
    """After run(), _last_synthesizer_input contains the merged input for the synthesis round."""
    from research_analysis_layer.services.agent_registry import AgentConfig
    from research_analysis_layer.services.agent_llm_client import (
        AgentCallResult,
        TokenUsage,
    )

    registry = MagicMock()
    registry.load_prompt.return_value = "system"
    input_builder = MagicMock()
    input_builder.build.return_value = {"base": {"document": {}}}
    input_builder.to_messages.return_value = []

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
        token_usage=TokenUsage(input_tokens=5, output_tokens=2),
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

    synth_round = RoundConfig(
        name="synthesis",
        type="sequential",
        agents=["synthesizer"],
        receives=["input"],
        output_schema="DocumentAnalysis",
        receives_forum_state=False,
        writes_forum_state=False,
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

    document = MagicMock(research_id=1, document_hash="abc", file_id=None)
    document.document = None
    document.themes = []

    assert ex._last_synthesizer_input is None  # starts empty
    ex.run(
        document=document,
        chunks=[],
        evidence_units=[],
        assertions=[],
        run_id=1,
        analysis_version="v1",
        rounds=[synth_round],
        agent_specs={"synthesizer": spec},
    )
    assert ex._last_synthesizer_input is not None
    assert "base" in ex._last_synthesizer_input


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
