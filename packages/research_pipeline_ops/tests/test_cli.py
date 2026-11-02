from __future__ import annotations

import research_pipeline_ops.cli as cli
from research_pipeline_ops.cli import build_parser


def test_check_json_arguments() -> None:
    args = build_parser().parse_args(["check", "--json"])
    assert args.command == "check"
    assert args.json is True


def test_retry_defaults_to_dry_run_false() -> None:
    args = build_parser().parse_args(["retry", "--incident", "incident:1"])
    assert args.actor == "nexus-ops-cli"
    assert args.dry_run is False


def test_doctor_requires_ingested_operations(monkeypatch) -> None:
    class FakeMonitor:
        def __init__(self, _database_url: str) -> None:
            pass

        def doctor(self) -> dict[str, bool | str]:
            return {
                "database_name": "nexus",
                "schema_exists": True,
                "jobs_exists": True,
                "ingested_operations_exists": False,
                "incidents_exists": True,
            }

    monkeypatch.setattr(cli, "PipelineOpsMonitor", FakeMonitor)
    monkeypatch.setenv("NEXUS_DATABASE_URL", "postgresql://unused")
    assert cli.main(["doctor"]) == 1
