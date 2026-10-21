"""Command-line interface for the Nexus batch operations control plane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from research_pipeline_ops.monitor import PipelineOpsMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus-ops", description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Defaults to PIPELINE_OPS_DATABASE_URL or NEXUS_DATABASE_URL",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check database and schema availability")

    check = subparsers.add_parser("check", help="Refresh and return the attention queue")
    check.add_argument("--json", action="store_true")

    incidents = subparsers.add_parser("incidents", help="List incidents")
    incidents.add_argument(
        "--status", choices=["open", "claimed", "resolved", "suppressed"], default="open"
    )
    incidents.add_argument("--json", action="store_true")

    claim = subparsers.add_parser("claim", help="Lease open incidents to one actor")
    claim.add_argument("--actor", required=True)
    claim.add_argument("--limit", type=int, default=5)
    claim.add_argument("--lease-minutes", type=int, default=20)
    claim.add_argument("--json", action="store_true")

    retry = subparsers.add_parser("retry", help="Perform an allowlisted incident retry")
    retry.add_argument("--incident", required=True)
    retry.add_argument("--actor", default="nexus-ops-cli")
    retry.add_argument("--dry-run", action="store_true")

    resolve = subparsers.add_parser("resolve", help="Resolve an incident manually")
    resolve.add_argument("--incident", required=True)
    resolve.add_argument("--actor", default="nexus-ops-cli")
    resolve.add_argument("--summary", required=True)

    decline = subparsers.add_parser("decline", help="Suppress an incident with a reason")
    decline.add_argument("--incident", required=True)
    decline.add_argument("--actor", default="nexus-ops-cli")
    decline.add_argument("--reason", required=True)
    return parser


def _database_url(argument: str | None) -> str:
    value = argument or os.getenv("PIPELINE_OPS_DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL")
    if not value:
        raise ValueError("set PIPELINE_OPS_DATABASE_URL or NEXUS_DATABASE_URL")
    return value


def _print_rows(rows: Sequence[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"count": len(rows), "items": list(rows)}, indent=2, sort_keys=True))
        return
    if not rows:
        print("healthy: no incidents need attention")
        return
    for row in rows:
        print(
            f"{row.get('severity', '-'):8} {row.get('status', '-'):10} "
            f"{row.get('job_key', '-'):38} {row.get('kind', '-'):10} "
            f"{row.get('incident_key', '-')}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        monitor = PipelineOpsMonitor(_database_url(args.database_url))
        if args.command == "doctor":
            result = monitor.doctor()
            print(json.dumps(result, indent=2, sort_keys=True))
            required_checks = ("schema_exists", "jobs_exists", "incidents_exists")
            return 0 if all(result[key] for key in required_checks) else 1
        if args.command == "check":
            rows = monitor.check()
            _print_rows(rows, as_json=args.json)
            return 0
        if args.command == "incidents":
            rows = monitor.list_incidents(status=args.status)
            _print_rows(rows, as_json=args.json)
            return 0
        if args.command == "claim":
            rows = monitor.claim(
                actor=args.actor,
                limit=args.limit,
                lease_minutes=args.lease_minutes,
            )
            _print_rows(rows, as_json=args.json)
            return 0
        if args.command == "retry":
            result = monitor.retry(
                incident_key=args.incident,
                actor=args.actor,
                dry_run=args.dry_run,
            )
        elif args.command == "resolve":
            result = monitor.resolve(
                incident_key=args.incident,
                actor=args.actor,
                summary=args.summary,
            )
        else:
            result = monitor.decline(
                incident_key=args.incident,
                actor=args.actor,
                reason=args.reason,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KeyError, ValueError, psycopg.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
