from unittest.mock import MagicMock


def test_doctor_prints_trigger_stats_when_enabled(capsys):
    from research_analysis_layer import main as main_module

    trigger = MagicMock()
    trigger.queue_depth = 3
    trigger.dropped_count = 7

    main_module._print_eval_trigger_stats(trigger)
    captured = capsys.readouterr().out
    assert "queue_depth=3" in captured
    assert "dropped=7" in captured
