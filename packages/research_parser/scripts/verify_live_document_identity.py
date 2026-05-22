#!/usr/bin/env python3
"""Live Supabase smoke test for parser document-identity upserts.

This script performs a minimal end-to-end verification against a live Supabase
project:

1. Insert a temporary parsed_research row through the same upsert helper used by
   the parser write path.
2. Upsert the same `(document_hash, document_name, source)` tuple again with a
   changed payload.
3. Assert that both writes resolve to the same row id and that the second write
   updated the row.
4. Delete the temporary row before exiting.

It is intended for post-migration verification after applying
`migrations/003_parsed_research_document_identity.sql`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

from src.storage.supabase import SupabaseClient, _compute_document_hash


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a live Supabase smoke test for parsed_research identity upserts."
        )
    )
    parser.add_argument(
        "--supabase-url",
        default=os.getenv("SUPABASE_URL"),
        help="Supabase project URL (or set SUPABASE_URL)",
    )
    parser.add_argument(
        "--supabase-key",
        default=os.getenv("SUPABASE_KEY"),
        help="Supabase service role key (or set SUPABASE_KEY)",
    )
    parser.add_argument(
        "--keep-row",
        action="store_true",
        help="Keep the temporary test row instead of deleting it",
    )
    return parser.parse_args()


def _build_record(*, source: str, document_name: str, document_hash: str, text: str) -> dict:
    return {
        "parsed_data": {
            "metadata": {
                "source": source,
                "source_date": "2026-04-14",
                "publisher": "codex",
                "area": "Other",
                "region": "Global",
                "asset_focus": "multi-asset",
                "document_link": None,
            },
            "themes": [],
            "trades": [],
            "full_text": text,
            "extraction_stats": {
                "num_themes": 0,
                "num_trades": 0,
                "extraction_method": "Codex live integration test",
                "metadata_ok": True,
                "themes_ok": True,
                "trades_ok": True,
            },
        },
        "source_date": "2026-04-14",
        "source": source,
        "document_name": document_name,
        "document_title": "Codex Live Upsert Test",
        "publisher": "codex",
        "area": "Other",
        "region": "Global",
        "asset_focus": "multi-asset",
        "document_link": None,
        "theme_count": 0,
        "trade_count": 0,
        "document_hash": document_hash,
    }


def main() -> int:
    args = parse_args()
    if not args.supabase_url or not args.supabase_key:
        print("Missing Supabase credentials. Provide --supabase-url/--supabase-key.")
        return 2

    client = SupabaseClient(args.supabase_url, args.supabase_key)
    table = client._client.table("parsed_research")

    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    source = f"codex-live-upsert-test-{suffix}"
    document_name = f"codex-live-{suffix}.txt"
    text = f"Codex live upsert smoke test {suffix}"
    document_hash = _compute_document_hash(text)

    cleanup_id: int | None = None

    try:
        existing = (
            table.select("id")
            .eq("document_hash", document_hash)
            .eq("document_name", document_name)
            .eq("source", source)
            .limit(5)
            .execute()
        )
        if existing.data:
            print(json.dumps({"status": "error", "error": "test_row_collision"}))
            return 1

        record1 = _build_record(
            source=source,
            document_name=document_name,
            document_hash=document_hash,
            text=text,
        )
        row1 = client._get_or_create_research_row(
            document_hash=document_hash,
            document_name=document_name,
            source=source,
            record=record1,
        )
        if not row1 or not row1.get("id"):
            print(json.dumps({"status": "error", "error": "first_upsert_failed"}))
            return 1
        cleanup_id = int(row1["id"])

        record2 = _build_record(
            source=source,
            document_name=document_name,
            document_hash=document_hash,
            text=text,
        )
        record2["trade_count"] = 1
        record2["parsed_data"]["trades"] = [
            {"text": "temp trade", "conviction": "Low", "timeframe": "days"}
        ]
        record2["parsed_data"]["extraction_stats"]["num_trades"] = 1

        row2 = client._get_or_create_research_row(
            document_hash=document_hash,
            document_name=document_name,
            source=source,
            record=record2,
        )
        if not row2 or not row2.get("id"):
            print(json.dumps({"status": "error", "error": "second_upsert_failed"}))
            return 1

        fetched = (
            table.select("id,trade_count,document_hash,document_name,source")
            .eq("id", cleanup_id)
            .limit(1)
            .execute()
        )
        fetched_row = fetched.data[0] if fetched.data else None
        if fetched_row is None:
            print(json.dumps({"status": "error", "error": "fetch_after_upsert_failed"}))
            return 1

        print(
            json.dumps(
                {
                    "status": "ok",
                    "first_id": row1["id"],
                    "second_id": row2["id"],
                    "same_row": row1["id"] == row2["id"],
                    "trade_count_after_second_upsert": fetched_row.get("trade_count"),
                    "document_name": document_name,
                    "source": source,
                },
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        if cleanup_id is not None and not args.keep_row:
            table.delete().eq("id", cleanup_id).execute()
            verify = table.select("id").eq("id", cleanup_id).limit(1).execute()
            print(
                json.dumps(
                    {
                        "cleanup_id": cleanup_id,
                        "cleanup_ok": not bool(verify.data),
                    },
                    sort_keys=True,
                )
            )


if __name__ == "__main__":
    raise SystemExit(main())
