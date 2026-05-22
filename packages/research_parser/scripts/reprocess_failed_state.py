#!/usr/bin/env python3
"""Force reprocess failed files from the local state database."""

from __future__ import annotations

import argparse
import sqlite3

from src.config import get_settings
from src.pipeline import Pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name-glob",
        default="*",
        help="SQLite GLOB pattern for file_name, e.g. '2026-05-*'.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum files to reprocess; 0 means no limit.",
    )
    parser.add_argument(
        "--file-id",
        action="append",
        default=[],
        help="Specific Drive file ID to reprocess. May be passed multiple times.",
    )
    parser.add_argument(
        "--theme-failures-only",
        action="store_true",
        help=(
            "Only reprocess low-cost rows where parse, metadata, and trades "
            "already succeeded but themes failed."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    query = """
        SELECT file_id, file_name
        FROM processed_files
        WHERE status = 'failed'
          AND file_name GLOB ?
    """
    params: list[object] = [args.name_glob]
    if args.theme_failures_only:
        query += """
          AND parse_ok = 1
          AND metadata_ok = 1
          AND themes_ok = 0
          AND trades_ok = 1
        """
    if args.file_id:
        placeholders = ",".join("?" for _ in args.file_id)
        query += f" AND file_id IN ({placeholders})"
        params.extend(args.file_id)

    query += " ORDER BY updated_at DESC, file_name"
    if args.limit > 0:
        query += " LIMIT ?"
        params.append(args.limit)

    with sqlite3.connect(settings.state_db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    print(f"failed_count={len(rows)}", flush=True)
    if not rows:
        return 0

    pipeline = Pipeline(settings)
    success_count = 0
    failed_names: list[str] = []
    for file_id, file_name in rows:
        print(f"REPROCESS_START {file_name}", flush=True)
        ok = pipeline.process_file(file_id, file_name)
        print(f"REPROCESS_DONE ok={ok} {file_name}", flush=True)
        if ok:
            success_count += 1
        else:
            failed_names.append(file_name)

    print(
        f"reprocessed_success={success_count} reprocessed_failed={len(failed_names)}",
        flush=True,
    )
    for name in failed_names:
        print(f"FAILED {name}", flush=True)
    return 0 if not failed_names else 1


if __name__ == "__main__":
    raise SystemExit(main())
