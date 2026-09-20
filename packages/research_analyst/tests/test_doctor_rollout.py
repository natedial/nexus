from unittest.mock import MagicMock
import sys
import types

if "research_pipeline_ops" not in sys.modules:
    stub = types.ModuleType("research_pipeline_ops")
    stub.PipelineOpsClient = MagicMock
    sys.modules["research_pipeline_ops"] = stub


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


def test_print_digest_consensus_stats_mode_only_when_off(capsys):
    from research_analysis_layer import main as m

    settings = MagicMock(digest_consensus_mode="off")
    m._print_digest_consensus_stats(settings, {"agreement_count": 2})
    out = capsys.readouterr().out
    assert "digest_consensus_mode=off" in out
    assert "digest_stats" not in out


def test_print_digest_consensus_stats_emitted_when_shadow(capsys):
    from research_analysis_layer import main as m

    settings = MagicMock(digest_consensus_mode="shadow")
    m._print_digest_consensus_stats(
        settings,
        {
            "agreement_count": 2,
            "disagreement_count": 1,
            "unresolved_referent_rate": 0.25,
        },
    )
    out = capsys.readouterr().out
    assert "digest_consensus_mode=shadow" in out
    assert "agreements=2" in out
    assert "disagreements=1" in out
    assert "unresolved_referent_rate=0.250" in out


def test_print_rubric_stats_includes_gate_and_rates(capsys):
    from research_analysis_layer import main as m

    m._print_rubric_stats(
        {
            "rates": {
                "claim_rationale_rate": 1.0,
                "claim_evidenced_rate": 0.5,
                "divergence_grounded_rate": 0.75,
                "divergence_attributed_rate": 1.0,
                "consensus_multi_source_rate": 0.0,
            },
            "promotion_gate": {
                "mode": "advisory",
                "action": "warn",
                "baseline_present": True,
                "failures": ["consensus_multi_source_rate"],
            },
        }
    )
    out = capsys.readouterr().out
    assert "promotion_gate: mode=advisory action=warn baseline=present" in out
    assert "claim_rationale_rate=1.000" in out
    assert "claim_evidenced_rate=0.500" in out
    assert "consensus_multi_source_rate=0.000" in out


def test_print_rollout_stats_includes_rubric_rates_when_numeric(capsys):
    from research_analysis_layer import main as m
    from research_analysis_layer.services.round_executor import RolloutStats

    executor = MagicMock()
    executor.debate_mode = "shadow"
    stats = RolloutStats(
        shadow_runs_total=1,
        claim_rationale_rate=0.9,
        claim_evidenced_rate=0.8,
        divergence_grounded_rate=0.7,
        divergence_attributed_rate=0.6,
        consensus_multi_source_rate=1.0,
    )
    executor.rollout_stats = stats
    m._print_rollout_stats(executor)
    out = capsys.readouterr().out
    assert "rollout_stats_rubric:" in out
    assert "claim_rationale_rate=0.900" in out
    assert "divergence_attributed_rate=0.600" in out
