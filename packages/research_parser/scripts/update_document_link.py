#!/usr/bin/env python3
"""Update stored document_link for a Google Drive file id."""

from __future__ import annotations

import argparse
import os
import sys

from supabase import create_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update document_link for a parsed_research record.",
    )
    parser.add_argument("--file-id", required=True, help="Google Drive file id")
    parser.add_argument("--new-link", required=True, help="Replacement URL")
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
        "--dry-run",
        action="store_true",
        help="Print matching records without updating",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.supabase_url or not args.supabase_key:
        print("Missing Supabase credentials. Provide --supabase-url/--supabase-key.")
        return 2

    client = create_client(args.supabase_url, args.supabase_key)

    response = (
        client.table("parsed_research")
        .select("id, parsed_data")
        .eq("document_id", args.file_id)
        .execute()
    )

    rows = response.data or []
    if not rows:
        print(f"No records found for document_id={args.file_id}")
        return 1

    if args.dry_run:
        print(f"Found {len(rows)} record(s) for document_id={args.file_id}")
        return 0

    updated = 0
    for row in rows:
        parsed_data = row.get("parsed_data") or {}
        metadata = parsed_data.get("metadata") or {}
        metadata["document_link"] = args.new_link
        parsed_data["metadata"] = metadata

        client.table("parsed_research").update(
            {"parsed_data": parsed_data, "document_link": args.new_link}
        ).eq("id", row["id"]).execute()
        updated += 1

    print(f"Updated {updated} record(s) for document_id={args.file_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
