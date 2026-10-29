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
