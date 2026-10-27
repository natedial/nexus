import json

import pytest

from research_gleaner.cli import _color_rules, _csv_env, _source_routes, build_parser, main
from research_gleaner.models import CaptureIntent


class FakeOps:
    def __init__(self):
        self.started = []
        self.finished = []
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        return 0

    def start_run(self, **kwargs):
        self.started.append(kwargs)
        return "gleaner:test-run"

    def finish_run(self, run_key, **kwargs):
        self.finished.append((run_key, kwargs))


def test_route_override_only_changes_intent():
    rules = _color_rules(["yellow=research", "green=relay"])

    assert rules["yellow"].intent == CaptureIntent.RESEARCH
    assert rules["green"].intent == CaptureIntent.RELAY


@pytest.mark.parametrize("route", ["yellow", "teal=research", "blue=send"])
def test_invalid_route_is_rejected(route):
    with pytest.raises(ValueError):
        _color_rules([route])


def test_missing_credentials_returns_usage_error(tmp_path, capsys, monkeypatch):
    ops = FakeOps()
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setattr("research_gleaner.cli.load_environment", lambda: None)
    monkeypatch.setattr(
        "research_gleaner.cli.PipelineOpsClient.from_env",
        lambda **_kwargs: ops,
    )
    result = main(
        [
            "notion",
            "--data-source-id",
            "source-1",
            "--state-db",
            str(tmp_path / "gleaner.db"),
        ]
    )

    assert result == 2
    assert "NOTION_TOKEN" in capsys.readouterr().err
    assert ops.started[0]["job_key"] == "gleaner.notion"
    assert ops.finished == [
        (
            "gleaner:test-run",
            {
                "status": "failed",
                "stats": None,
                "error_text": "NOTION_TOKEN is required",
                "exit_code": 2,
            },
        )
    ]


def test_overlapping_notion_sweep_is_recorded_as_skipped(tmp_path, capsys, monkeypatch):
    ops = FakeOps()
    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    monkeypatch.setattr("research_gleaner.cli.load_environment", lambda: None)
    monkeypatch.setattr(
        "research_gleaner.cli.PipelineOpsClient.from_env",
        lambda **_kwargs: ops,
    )

    class BusyLock:
        def __init__(self, _path):
            pass

        def __enter__(self):
            from research_gleaner.lock import AlreadyRunningError

            raise AlreadyRunningError("already running")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("research_gleaner.cli.RunLock", BusyLock)
    result = main(
        [
            "notion",
            "--data-source-id",
            "source-1",
            "--state-db",
            str(tmp_path / "gleaner.db"),
            "--lock-file",
            str(tmp_path / "gleaner.lock"),
        ]
    )

    assert result == 0
    assert "skipped" in capsys.readouterr().out
    assert ops.finished[-1][1]["status"] == "skipped"
    assert ops.finished[-1][1]["exit_code"] == 0


def test_query_returns_json_without_notion_credentials(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.setattr("research_gleaner.cli.load_environment", lambda: None)
    monkeypatch.setattr(
        "research_gleaner.cli.PipelineOpsClient.from_env",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("query must not emit ops")),
    )

    result = main(["query", "--state-db", str(tmp_path / "gleaner.db")])

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {"count": 0, "captures": []}


def test_sweep_profile_defaults_come_from_environment(monkeypatch):
    monkeypatch.setenv("RESEARCH_GLEANER_NOTION_TOPIC", "Markets")
    monkeypatch.setenv("RESEARCH_GLEANER_NOTION_SINCE", "24h")

    args = build_parser().parse_args(["notion"])

    assert args.topic == "Markets"
    assert args.since == "24h"


def test_csv_environment_values_are_trimmed(monkeypatch):
    monkeypatch.setenv(
        "RESEARCH_GLEANER_NOTION_RESOURCE_TYPES",
        "Research Note, Commentary,",
    )

    assert _csv_env("RESEARCH_GLEANER_NOTION_RESOURCE_TYPES") == [
        "Research Note",
        "Commentary",
    ]


def test_remarkable_defaults_to_24_hour_lookback(monkeypatch):
    monkeypatch.delenv("RESEARCH_GLEANER_REMARKABLE_SINCE", raising=False)

    args = build_parser().parse_args(["remarkable"])

    assert args.since == "24h"


def test_remarkable_routes_accept_recorded_color_names():
    assert _source_routes(["pink=research", "gray=relay"]) == {
        "pink": CaptureIntent.RESEARCH,
        "gray": CaptureIntent.RELAY,
    }
