import argparse

from research_relay import cli
from research_relay.cli import parse_cli


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
        return "relay:test-run"

    def finish_run(self, run_key, **kwargs):
        self.finished.append((run_key, kwargs))


def test_config_flag_after_auth_subcommand() -> None:
    args = parse_cli(["auth", "--config", "/tmp/relay.toml"])
    assert args.command == "auth"
    assert args.config == "/tmp/relay.toml"


def test_config_flag_before_auth_subcommand() -> None:
    args = parse_cli(["--config", "/tmp/relay.toml", "auth"])
    assert args.command == "auth"
    assert args.config == "/tmp/relay.toml"


def test_config_flag_after_health_subcommand() -> None:
    args = parse_cli(["health", "--config", "/tmp/relay.toml"])
    assert args.command == "health"
    assert args.config == "/tmp/relay.toml"


def test_run_accepts_config_and_dry_run() -> None:
    args = parse_cli(["run", "--config", "/tmp/relay.toml", "--dry-run"])
    assert args.command == "run"
    assert args.config == "/tmp/relay.toml"
    assert args.dry_run is True


def test_run_accepts_max_messages() -> None:
    args = parse_cli(["run", "--live", "--max-messages", "200"])
    assert args.live is True
    assert args.max_messages == 200


def test_run_accepts_max_runtime() -> None:
    args = parse_cli(["run", "--live", "--max-runtime", "240"])
    assert args.max_runtime == 240


def test_breaker_reset_subcommand() -> None:
    args = parse_cli(["breaker-reset", "--config", "/tmp/relay.toml"])
    assert args.command == "breaker-reset"
    assert args.config == "/tmp/relay.toml"


def test_alert_test_subcommand() -> None:
    args = parse_cli(["alert-test", "--config", "/tmp/relay.toml"])
    assert args.command == "alert-test"
    assert args.config == "/tmp/relay.toml"


def test_archive_subcommand_flags() -> None:
    args = parse_cli(["archive", "--live", "--force", "--key", "proton:<a@b>", "--limit", "100"])
    assert args.command == "archive"
    assert args.live is True
    assert args.force is True
    assert args.key == "proton:<a@b>"
    assert args.limit == 100


def test_archive_status_subcommand() -> None:
    args = parse_cli(["archive-status", "--config", "/tmp/relay.toml"])
    assert args.command == "archive-status"


def test_archive_enqueue_subcommand_flags() -> None:
    args = parse_cli(["archive-enqueue", "--hours", "48", "--limit", "20", "--dry-run"])
    assert args.command == "archive-enqueue"
    assert args.hours == 48
    assert args.limit == 20
    assert args.dry_run is True
    assert not hasattr(args, "live") or getattr(args, "live", False) is False


def test_archive_enqueue_since_flag() -> None:
    args = parse_cli(["archive-enqueue", "--since", "2026-08-15"])
    assert args.command == "archive-enqueue"
    assert args.since == "2026-08-15"
    assert args.hours is None
    assert args.limit is None


def test_tracked_command_records_allowlisted_degraded_outcome(monkeypatch, tmp_path):
    ops = FakeOps()
    monkeypatch.setenv("RESEARCH_RELAY_PIPELINE_OPS_SPOOL", str(tmp_path / "ops.db"))
    monkeypatch.setattr(cli.PipelineOpsClient, "from_env", lambda **_kwargs: ops)

    def fake_run(_args, *, ops_outcome):
        ops_outcome.record("degraded", stats={"temporary_failures": 1})
        return 1

    monkeypatch.setattr(cli, "_run_command", fake_run)
    result = cli._run_with_ops(argparse.Namespace(command="run"), job_key="relay.email")

    assert result == 1
    assert ops.started[0]["job_key"] == "relay.email"
    assert ops.finished == [
        (
            "relay:test-run",
            {
                "status": "degraded",
                "stats": {"temporary_failures": 1},
                "error_text": None,
                "exit_code": 1,
            },
        )
    ]
    assert ops.flush_count == 2


def test_tracked_command_records_exception_class_only(monkeypatch, tmp_path):
    ops = FakeOps()
    monkeypatch.setenv("RESEARCH_RELAY_PIPELINE_OPS_SPOOL", str(tmp_path / "ops.db"))
    monkeypatch.setattr(cli.PipelineOpsClient, "from_env", lambda **_kwargs: ops)

    def fail(_args, *, ops_outcome):
        del ops_outcome
        raise RuntimeError("private@example.com secret subject")

    monkeypatch.setattr(cli, "_run_command", fail)

    try:
        cli._run_with_ops(argparse.Namespace(command="archive"), job_key="relay.archive")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert ops.finished[-1][1]["status"] == "failed"
    assert ops.finished[-1][1]["error_text"] == "RuntimeError"
