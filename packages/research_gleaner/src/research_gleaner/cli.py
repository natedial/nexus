from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from research_pipeline_ops import PipelineOpsClient

from research_gleaner.env import load_environment
from research_gleaner.lock import AlreadyRunningError, RunLock
from research_gleaner.models import CaptureIntent
from research_gleaner.notion.client import DEFAULT_NOTION_VERSION, NotionClient, NotionError
from research_gleaner.notion.extractor import DEFAULT_COLOR_RULES, ColorRule
from research_gleaner.notion.query import NotionQuery, parse_since
from research_gleaner.pipeline import run_notion_capture, run_remarkable_capture
from research_gleaner.remarkable.client import RemarkableLibrary
from research_gleaner.store import CaptureStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-gleaner",
        description="Capture source-grounded highlights for Nexus",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    notion = subparsers.add_parser("notion", help="Capture colored text from Notion")
    notion.add_argument(
        "--data-source-id",
        default=os.getenv("RESEARCH_GLEANER_NOTION_DATA_SOURCE_ID"),
        help="Notion data source ID (default: RESEARCH_GLEANER_NOTION_DATA_SOURCE_ID)",
    )
    notion.add_argument(
        "--topic",
        default=os.getenv("RESEARCH_GLEANER_NOTION_TOPIC"),
        help="Topics multi-select value",
    )
    notion.add_argument(
        "--resource-type",
        action="append",
        default=None,
        help="Resource Type multi-select value; repeat for multiple values",
    )
    notion.add_argument(
        "--since",
        default=os.getenv("RESEARCH_GLEANER_NOTION_SINCE"),
        help="Lookback such as 24h or 7d",
    )
    notion.add_argument("--title-property", default="Name")
    notion.add_argument("--topics-property", default="Topics")
    notion.add_argument("--resource-type-property", default="Resource Type")
    notion.add_argument(
        "--route",
        action="append",
        default=None,
        metavar="COLOR=INTENT",
        help="Route a Notion color to hold, research, relay, or both",
    )
    notion.add_argument(
        "--lock-file",
        type=Path,
        default=Path(
            os.getenv(
                "RESEARCH_GLEANER_LOCK_FILE",
                "~/.local/state/research-gleaner/notion-sweep.lock",
            )
        ).expanduser(),
    )
    notion.add_argument(
        "--state-db",
        type=Path,
        default=Path(
            os.getenv(
                "RESEARCH_GLEANER_STATE_DB",
                "~/.local/state/research-gleaner/gleaner.db",
            )
        ).expanduser(),
    )
    notion.add_argument("--out", type=Path, default=None)
    notion.add_argument("--api-version", default=DEFAULT_NOTION_VERSION)
    remarkable = subparsers.add_parser(
        "remarkable", help="Capture native PDF highlights from reMarkable"
    )
    remarkable.add_argument(
        "--since",
        default=os.getenv("RESEARCH_GLEANER_REMARKABLE_SINCE", "24h"),
        help="Only inspect documents modified in this lookback (default: 24h)",
    )
    remarkable.add_argument(
        "--route",
        action="append",
        default=None,
        metavar="COLOR=INTENT",
        help="Route a reMarkable color to hold, research, relay, or both",
    )
    remarkable.add_argument(
        "--lock-file",
        type=Path,
        default=Path(
            os.getenv(
                "RESEARCH_GLEANER_REMARKABLE_LOCK_FILE",
                "~/.local/state/research-gleaner/remarkable-sweep.lock",
            )
        ).expanduser(),
    )
    remarkable.add_argument(
        "--state-db",
        type=Path,
        default=Path(
            os.getenv(
                "RESEARCH_GLEANER_STATE_DB",
                "~/.local/state/research-gleaner/gleaner.db",
            )
        ).expanduser(),
    )
    remarkable.add_argument("--out", type=Path, default=None)
    query = subparsers.add_parser("query", help="Query stored captures as JSON")
    query.add_argument("--text", help="Full-text search terms")
    query.add_argument("--source-kind", help="Filter by source, such as notion")
    query.add_argument("--source-style", help="Filter by recorded source style or color")
    query.add_argument("--intent", choices=[item.value for item in CaptureIntent])
    query.add_argument("--document", help="Case-insensitive document title substring")
    query.add_argument("--since", help="Filter by first ingestion time, such as 24h or 7d")
    query.add_argument("--include-inactive", action="store_true")
    query.add_argument("--compact", action="store_true", help="Return concise evidence fields")
    query.add_argument("--limit", type=int, default=50)
    query.add_argument(
        "--state-db",
        type=Path,
        default=Path(
            os.getenv(
                "RESEARCH_GLEANER_STATE_DB",
                "~/.local/state/research-gleaner/gleaner.db",
            )
        ).expanduser(),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_environment()
    args = build_parser().parse_args(argv)
    if args.command == "query":
        return _run_query(args)
    if args.command == "remarkable":
        return _run_remarkable(args)
    return _run_notion(args)


def _run_notion(args: argparse.Namespace) -> int:
    ops, run_key = _start_ops_run(args, job_key="gleaner.notion", run_type="notion")
    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        print("error: NOTION_TOKEN is required", file=sys.stderr)
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text="NOTION_TOKEN is required",
            exit_code=2,
        )
        return 2
    if not args.data_source_id:
        message = "--data-source-id or RESEARCH_GLEANER_NOTION_DATA_SOURCE_ID is required"
        print(f"error: {message}", file=sys.stderr)
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text=message,
            exit_code=2,
        )
        return 2
    try:
        resource_types = args.resource_type or _csv_env("RESEARCH_GLEANER_NOTION_RESOURCE_TYPES")
        routes = args.route or _csv_env("RESEARCH_GLEANER_NOTION_ROUTES")
        rules = _color_rules(routes)
        query = NotionQuery(
            data_source_id=args.data_source_id,
            topic=args.topic,
            resource_types=tuple(resource_types),
            since=args.since,
            title_property=args.title_property,
            topics_property=args.topics_property,
            resource_type_property=args.resource_type_property,
        )
        output_path = args.out or _default_output_path()
        store = CaptureStore(args.state_db)
        with RunLock(args.lock_file):
            with NotionClient(token, api_version=args.api_version) as client:
                batch = run_notion_capture(
                    client,
                    store,
                    query,
                    output_path,
                    color_rules=rules,
                )
    except AlreadyRunningError as exc:
        print(f"skipped: {exc}")
        _finish_ops_run(ops, run_key, status="skipped", exit_code=0)
        return 0
    except (ValueError, NotionError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text=str(exc),
            exit_code=1,
        )
        return 1
    except Exception as exc:
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text=str(exc),
            exit_code=1,
        )
        raise
    print(
        f"captured={len(batch.captures)} new={len(batch.new_capture_ids)} "
        f"output={output_path.expanduser()}"
    )
    _finish_ops_run(
        ops,
        run_key,
        status="succeeded",
        stats={
            "capture_count": len(batch.captures),
            "new_capture_count": len(batch.new_capture_ids),
        },
        exit_code=0,
    )
    return 0


def _run_query(args: argparse.Namespace) -> int:
    try:
        since = parse_since(args.since) if args.since else None
        rows = CaptureStore(args.state_db).search(
            text=args.text,
            source_kind=args.source_kind,
            source_style=args.source_style,
            intent=args.intent,
            document=args.document,
            first_seen_since=since,
            active_only=not args.include_inactive,
            limit=args.limit,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    captures = [_compact_capture(row) for row in rows] if args.compact else rows
    json.dump(
        {"count": len(captures), "captures": captures},
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    print()
    return 0


def _run_remarkable(args: argparse.Namespace) -> int:
    ops, run_key = _start_ops_run(
        args,
        job_key="gleaner.remarkable",
        run_type="remarkable",
    )
    try:
        routes = _source_routes(args.route or _csv_env("RESEARCH_GLEANER_REMARKABLE_ROUTES"))
        output_path = args.out or _default_output_path("remarkable")
        store = CaptureStore(args.state_db)
        with RunLock(args.lock_file):
            batch = run_remarkable_capture(
                RemarkableLibrary(),
                store,
                output_path,
                modified_since=parse_since(args.since),
                routes=routes,
            )
    except AlreadyRunningError as exc:
        print(f"skipped: {exc}")
        _finish_ops_run(ops, run_key, status="skipped", exit_code=0)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text=str(exc),
            exit_code=1,
        )
        return 1
    except Exception as exc:
        _finish_ops_run(
            ops,
            run_key,
            status="failed",
            error_text=str(exc),
            exit_code=1,
        )
        raise
    print(
        f"captured={len(batch.captures)} new={len(batch.new_capture_ids)} "
        f"output={output_path.expanduser()}"
    )
    _finish_ops_run(
        ops,
        run_key,
        status="succeeded",
        stats={
            "capture_count": len(batch.captures),
            "new_capture_count": len(batch.new_capture_ids),
        },
        exit_code=0,
    )
    return 0


def _start_ops_run(
    args: argparse.Namespace,
    *,
    job_key: str,
    run_type: str,
) -> tuple[PipelineOpsClient, str | None]:
    spool_path = args.state_db.expanduser().parent / "pipeline_ops_spool.db"
    ops = PipelineOpsClient.from_env(
        default_spool_db_path=spool_path,
        emitted_by="research_gleaner",
    )
    ops.flush()
    run_key = ops.start_run(
        job_key=job_key,
        repo_name="research_gleaner",
        stage_family="gleaner",
        run_type=run_type,
        trigger_source=os.getenv("PIPELINE_OPS_TRIGGER_SOURCE", "manual"),
    )
    return ops, run_key


def _finish_ops_run(
    ops: PipelineOpsClient,
    run_key: str | None,
    *,
    status: str,
    stats: dict[str, object] | None = None,
    error_text: str | None = None,
    exit_code: int,
) -> None:
    ops.finish_run(
        run_key,
        status=status,
        stats=stats,
        error_text=error_text,
        exit_code=exit_code,
    )
    ops.flush()


def _color_rules(routes: list[str]) -> dict[str, ColorRule]:
    rules = dict(DEFAULT_COLOR_RULES)
    for value in routes:
        color, separator, intent_text = value.partition("=")
        color = color.strip().lower()
        if not separator or not color or not intent_text.strip():
            raise ValueError(f"invalid --route {value!r}; expected COLOR=INTENT")
        if color not in rules:
            raise ValueError(f"unknown Notion color in --route: {color}")
        try:
            intent = CaptureIntent(intent_text.strip().lower())
        except ValueError as exc:
            choices = ", ".join(item.value for item in CaptureIntent)
            raise ValueError(f"invalid capture intent {intent_text!r}; choose {choices}") from exc
        rules[color] = ColorRule(intent=intent)
    return rules


def _source_routes(routes: list[str]) -> dict[str, CaptureIntent]:
    parsed = {}
    for value in routes:
        color, separator, intent_text = value.partition("=")
        color = color.strip().lower()
        if not separator or not color or not intent_text.strip():
            raise ValueError(f"invalid --route {value!r}; expected COLOR=INTENT")
        try:
            parsed[color] = CaptureIntent(intent_text.strip().lower())
        except ValueError as exc:
            choices = ", ".join(item.value for item in CaptureIntent)
            raise ValueError(f"invalid capture intent {intent_text!r}; choose {choices}") from exc
    return parsed


def _default_output_path(source_kind: str = "notion") -> Path:
    directory = Path(
        os.getenv("RESEARCH_GLEANER_OUTPUT_DIR", "~/research-gleaner/out")
    ).expanduser()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{stamp}-{source_kind}-captures.json"


def _csv_env(name: str) -> list[str]:
    return [part.strip() for part in os.getenv(name, "").split(",") if part.strip()]


def _compact_capture(row: dict) -> dict:
    payload = row["payload"]
    return {
        "capture_id": row["capture_id"],
        "source_kind": row["source_kind"],
        "document_id": row["document_id"],
        "document_title": row["document_title"],
        "document_uri": row["document_uri"],
        "source_style": row["source_style"],
        "intent": row["intent"],
        "text": row["text"],
        "page_number": row["page_number"],
        "locator": payload.get("locator"),
        "first_seen_at": row["first_seen_at"],
        "active": row["active"],
    }
