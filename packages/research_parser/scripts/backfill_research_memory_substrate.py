#!/usr/bin/env python3
"""Backfill research memory substrate tables from parsed_research.full_text.

Deprecated (Phase 2): still uses Supabase PostgREST. Prefer re-derive via parser
re-parse into PostgreSQL instead of running this script.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.research_memory.backfill import (
    DEFAULT_CHUNKER_VERSION,
    DEFAULT_PARSER_VERSION,
    DEFAULT_SPAN_VERSION,
    build_backfill_records,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--resume-from", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--research-id", action="append", type=int, default=[])
    parser.add_argument("--parser-version", default=DEFAULT_PARSER_VERSION)
    parser.add_argument("--span-version", default=DEFAULT_SPAN_VERSION)
    parser.add_argument("--chunker-version", default=DEFAULT_CHUNKER_VERSION)
    parser.add_argument("--target-chars", type=int, default=6000)
    parser.add_argument("--min-chars", type=int, default=1800)
    parser.add_argument("--overlap-spans", type=int, default=1)
    parser.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Delete existing artifact/span/chunk rows for the selected versions before inserting. "
            "Use only before downstream evidence references these rows."
        ),
    )
    parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help="Required with --replace to acknowledge destructive replacement of existing rows.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be positive when provided")
    if args.min_chars <= 0 or args.target_chars <= 0:
        raise SystemExit("--min-chars and --target-chars must be positive")
    if args.overlap_spans < 0:
        raise SystemExit("--overlap-spans must be non-negative")
    if args.replace and not args.confirm_replace:
        raise SystemExit("--replace requires --confirm-replace")


def fetch_batch(
    client: Any,
    *,
    batch_size: int,
    last_id: int | None,
    research_ids: list[int],
) -> list[dict[str, Any]]:
    query = client.table("parsed_research").select(
        "id, document_hash, document_name, source, source_date, parsed_data"
    )
    if research_ids:
        query = query.in_("id", research_ids)
    elif last_id is not None:
        query = query.gt("id", last_id)

    response = query.order("id").limit(batch_size).execute()
    return response.data or []


def delete_existing(
    client: Any,
    *,
    research_id: int,
    parser_version: str,
    span_version: str,
    chunker_version: str,
) -> None:
    client.table("research_document_artifacts").delete().eq("research_id", research_id).eq(
        "parser_version", parser_version
    ).execute()
    client.table("research_retrieval_chunks").delete().eq("research_id", research_id).eq(
        "chunker_version", chunker_version
    ).execute()
    client.table("research_spans").delete().eq("research_id", research_id).eq(
        "span_version", span_version
    ).execute()


def _fetch_existing(
    client: Any,
    *,
    table: str,
    research_id: int,
    version_column: str,
    version: str,
    columns: str,
) -> list[dict[str, Any]]:
    response = (
        client.table(table)
        .select(columns)
        .eq("research_id", research_id)
        .eq(version_column, version)
        .execute()
    )
    return response.data or []


def _count_existing(
    client: Any,
    *,
    table: str,
    research_id: int,
    version_column: str,
    version: str,
) -> int:
    return len(
        _fetch_existing(
            client,
            table=table,
            research_id=research_id,
            version_column=version_column,
            version=version,
            columns="id",
        )
    )


def replacement_counts(
    client: Any,
    *,
    research_id: int,
    parser_version: str,
    span_version: str,
    chunker_version: str,
) -> dict[str, int]:
    return {
        "artifacts": _count_existing(
            client,
            table="research_document_artifacts",
            research_id=research_id,
            version_column="parser_version",
            version=parser_version,
        ),
        "spans": _count_existing(
            client,
            table="research_spans",
            research_id=research_id,
            version_column="span_version",
            version=span_version,
        ),
        "chunks": _count_existing(
            client,
            table="research_retrieval_chunks",
            research_id=research_id,
            version_column="chunker_version",
            version=chunker_version,
        ),
    }


def _key_drift_messages(
    *,
    label: str,
    existing_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    order_column: str,
    key_column: str,
) -> list[str]:
    existing_by_order = {
        int(row[order_column]): row[key_column]
        for row in existing_rows
        if row.get(order_column) is not None and row.get(key_column) is not None
    }
    messages = []
    for row in new_rows:
        order = int(row[order_column])
        existing_key = existing_by_order.get(order)
        new_key = row[key_column]
        if existing_key is not None and existing_key != new_key:
            messages.append(
                f"{label} order={order} existing_key={existing_key} new_key={new_key}"
            )
    return messages


def validate_no_key_drift(client: Any, records: dict[str, Any]) -> None:
    research_id = int(records["artifact"]["research_id"])
    span_version = records["artifact"]["artifact_manifest"]["span_version"]
    chunker_version = records["artifact"]["artifact_manifest"]["chunker_version"]

    messages = []
    messages.extend(
        _key_drift_messages(
            label="span",
            existing_rows=_fetch_existing(
                client,
                table="research_spans",
                research_id=research_id,
                version_column="span_version",
                version=span_version,
                columns="span_order,span_key",
            ),
            new_rows=records["spans"],
            order_column="span_order",
            key_column="span_key",
        )
    )
    messages.extend(
        _key_drift_messages(
            label="chunk",
            existing_rows=_fetch_existing(
                client,
                table="research_retrieval_chunks",
                research_id=research_id,
                version_column="chunker_version",
                version=chunker_version,
                columns="chunk_order,chunk_key",
            ),
            new_rows=records["chunks"],
            order_column="chunk_order",
            key_column="chunk_key",
        )
    )
    if messages:
        details = "; ".join(messages[:5])
        raise ValueError(
            f"research_id={research_id} existing same-version memory rows have different keys; "
            f"use --replace --confirm-replace to rebuild them. {details}"
        )


def write_records(client: Any, records: dict[str, Any]) -> None:
    client.table("research_document_artifacts").upsert(
        records["artifact"],
        on_conflict="research_id,parser_version",
    ).execute()

    spans = records["spans"]
    if spans:
        client.table("research_spans").upsert(spans, on_conflict="span_key").execute()

    chunks = records["chunks"]
    if chunks:
        client.table("research_retrieval_chunks").upsert(
            chunks,
            on_conflict="chunk_key",
        ).execute()


def process_record(client: Any, row: dict[str, Any], args: argparse.Namespace) -> tuple[int, int]:
    records = build_backfill_records(
        row,
        parser_version=args.parser_version,
        span_version=args.span_version,
        chunker_version=args.chunker_version,
        target_chars=args.target_chars,
        min_chars=args.min_chars,
        overlap_spans=args.overlap_spans,
    )

    research_id = int(row["id"])
    span_count = len(records["spans"])
    chunk_count = len(records["chunks"])

    if args.dry_run:
        print(
            f"  [DRY RUN] research_id={research_id} "
            f"spans={span_count} chunks={chunk_count}",
            flush=True,
        )
        return span_count, chunk_count

    if args.replace:
        counts = replacement_counts(
            client,
            research_id=research_id,
            parser_version=args.parser_version,
            span_version=args.span_version,
            chunker_version=args.chunker_version,
        )
        print(
            "  REPLACE WARNING: deleting generated memory rows can null evidence "
            "provenance through ON DELETE SET NULL. Use only before downstream "
            "evidence/claim tables reference these spans or chunks.",
            flush=True,
        )
        print(
            f"  [REPLACE] research_id={research_id} "
            f"artifacts={counts['artifacts']} spans={counts['spans']} chunks={counts['chunks']}",
            flush=True,
        )
        delete_existing(
            client,
            research_id=research_id,
            parser_version=args.parser_version,
            span_version=args.span_version,
            chunker_version=args.chunker_version,
        )
    else:
        validate_no_key_drift(client, records)

    write_records(client, records)
    return span_count, chunk_count


def main() -> int:
    args = parse_args()
    validate_args(args)

    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_key)

    print("Starting research memory substrate backfill")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Resume from: {args.resume_from or 'beginning'}")
    print(f"  Limit: {args.limit or 'none'}")
    print(f"  Research IDs: {args.research_id or 'all'}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Replace: {args.replace}")
    print(f"  Parser version: {args.parser_version}")
    print(f"  Span version: {args.span_version}")
    print(f"  Chunker version: {args.chunker_version}")

    total_processed = 0
    total_skipped = 0
    total_errors = 0
    total_spans = 0
    total_chunks = 0
    last_id = args.resume_from
    remaining = args.limit

    while True:
        batch_size = min(args.batch_size, remaining) if remaining else args.batch_size
        rows = fetch_batch(
            client,
            batch_size=batch_size,
            last_id=last_id,
            research_ids=args.research_id,
        )
        if not rows:
            break

        print(f"Processing IDs {rows[0]['id']}-{rows[-1]['id']}", flush=True)

        for row in rows:
            research_id = row.get("id")
            try:
                span_count, chunk_count = process_record(client, row, args)
                total_processed += 1
                total_spans += span_count
                total_chunks += chunk_count
            except ValueError as exc:
                print(f"  SKIP research_id={research_id}: {exc}", flush=True)
                total_skipped += 1
            except Exception as exc:
                print(f"  ERROR research_id={research_id}: {exc}", flush=True)
                total_errors += 1

        last_id = max(int(row["id"]) for row in rows)
        if remaining:
            remaining -= len(rows)
            if remaining <= 0:
                break
        if args.research_id or len(rows) < batch_size:
            break
        time.sleep(args.delay)

    print("=" * 60)
    print("Research memory substrate backfill complete")
    print(f"  Processed: {total_processed}")
    print(f"  Skipped: {total_skipped}")
    print(f"  Errors: {total_errors}")
    print(f"  Spans: {total_spans}")
    print(f"  Chunks: {total_chunks}")
    print(f"  Last ID: {last_id}")
    print("=" * 60)

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
