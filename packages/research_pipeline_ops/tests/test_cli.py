from __future__ import annotations

from research_pipeline_ops.cli import build_parser


def test_check_json_arguments() -> None:
    args = build_parser().parse_args(["check", "--json"])
    assert args.command == "check"
    assert args.json is True


def test_retry_defaults_to_dry_run_false() -> None:
    args = build_parser().parse_args(["retry", "--incident", "incident:1"])
    assert args.actor == "nexus-ops-cli"
    assert args.dry_run is False


def test_reap_stale_defaults_to_dry_run() -> None:
    args = build_parser().parse_args(["reap-stale"])
    assert args.command == "reap-stale"
    assert args.apply is False
    assert args.job_key is None
    assert args.json is False


def test_reap_stale_apply_and_job_filter() -> None:
    args = build_parser().parse_args(
        ["reap-stale", "--apply", "--job", "parser.poll", "--json"]
    )
    assert args.apply is True
    assert args.job_key == "parser.poll"
    assert args.json is True
