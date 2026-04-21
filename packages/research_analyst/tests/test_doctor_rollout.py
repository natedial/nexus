from unittest.mock import MagicMock


def test_print_rollout_stats_omitted_when_off(capsys):
    from research_analysis_layer import main as m

    executor = MagicMock()
    executor.debate_mode = "off"
    m._print_rollout_stats(executor)
    out = capsys.readouterr().out
    assert "debate_mode=off" in out
    assert "rollout_stats" not in out


def test_print_rollout_stats_emitted_when_shadow(capsys):
    from research_analysis_layer import main as m

    executor = MagicMock()
    executor.debate_mode = "shadow"
    executor.rollout_stats = MagicMock(
        shadow_runs_total=3,
        shadow_failures_total=1,
        debate_input_tokens=100,
        debate_output_tokens=50,
        baseline_input_tokens=20,
        baseline_output_tokens=10,
        debate_duration_ms=9000,
        baseline_duration_ms=3000,
    )
    m._print_rollout_stats(executor)
    out = capsys.readouterr().out
    assert "debate_mode=shadow" in out
    assert "shadow_runs=3" in out
    assert "shadow_failures=1" in out


def test_print_rollout_stats_none_executor_prints_nothing(capsys):
    from research_analysis_layer import main as m

    m._print_rollout_stats(None)
    assert capsys.readouterr().out == ""


def test_print_rollout_stats_none_executor_with_settings_prints_mode(capsys):
    from research_analysis_layer import main as m

    settings = MagicMock(analyst_debate_mode="shadow")
    m._print_rollout_stats(None, settings=settings)
    out = capsys.readouterr().out
    assert "debate_mode=shadow" in out
    assert "rollout_stats" not in out
