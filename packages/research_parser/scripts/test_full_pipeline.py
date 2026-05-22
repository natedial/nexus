#!/usr/bin/env python3
"""Test the full pipeline end-to-end."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings
from src.pipeline import Pipeline


def parse_args():
    parser = argparse.ArgumentParser(description="Test the full pipeline end-to-end.")
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="Exact PDF name to process (repeatable). If omitted, processes up to 3 new PDFs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess PDFs even if they were already processed.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional path to write logs (in addition to stdout).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only consider PDFs created on/after this date (YYYY-MM-DD, UTC).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.log_file:
        try:
            log_path = Path(args.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            sys.stdout = open(log_path, "w")
            sys.stderr = sys.stdout
        except Exception as e:
            print(f"Failed to open log file {args.log_file}: {e}")
    print("=" * 60)
    if args.pdf:
        print("FULL PIPELINE TEST (selected PDFs)")
    else:
        print("FULL PIPELINE TEST (max 3 PDFs)")
    print("=" * 60)

    print("\nInitializing pipeline...")
    settings = get_settings()
    pipeline = Pipeline(settings)

    print("\nFinding new PDFs to process...")
    since_dt = None
    if args.since:
        try:
            since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            print("Invalid --since value. Use YYYY-MM-DD (UTC).")
            return

    all_files = pipeline.drive.list_pdfs(since=since_dt)
    if args.force:
        new_files = list(all_files)
    else:
        new_files = [f for f in all_files if not pipeline.state.is_processed(f.id)]

    if args.pdf:
        requested = {name.strip() for name in args.pdf if name.strip()}
        files_to_process = [f for f in new_files if f.name in requested]
        missing = sorted(requested - {f.name for f in files_to_process})
        if missing:
            print("Warning: requested PDFs not found among new files:")
            for name in missing:
                print(f"  - {name}")
    else:
        # Limit to 3 PDFs
        files_to_process = new_files[:3]

    if not files_to_process:
        print("No new files to process.")
        return

    print(f"Found {len(new_files)} new file(s), processing {len(files_to_process)}:\n")
    for f in files_to_process:
        print(f"  - {f.name}")

    print("\nProcessing files...\n")
    processed = 0
    for file in files_to_process:
        try:
            success = pipeline.process_file(file.id, file.name)
            if success:
                processed += 1
        except Exception as e:
            print(f"Error processing {file.name}: {e}")

    print("\n" + "=" * 60)
    print(f"RESULT: Processed {processed} file(s)")
    print("=" * 60)

    # Show state of recently processed files
    print("\nRecent processing states:")
    from src.storage.state import StateStore
    state = StateStore(settings.state_db_path)

    # Get all records
    import sqlite3
    with sqlite3.connect(settings.state_db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT file_name, status, parse_ok, metadata_ok, themes_ok, trades_ok, storage_ok "
            "FROM processed_files ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()

        for row in rows:
            print(f"\n  {row['file_name'][:60]}...")
            print(f"    Status: {row['status']}")
            print(f"    Steps: parse={row['parse_ok']} meta={row['metadata_ok']} "
                  f"themes={row['themes_ok']} trades={row['trades_ok']} "
                  f"storage={row['storage_ok']}")


if __name__ == "__main__":
    main()
