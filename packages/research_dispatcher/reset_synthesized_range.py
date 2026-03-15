#!/usr/bin/env python3
"""Reset the parsed_research.synthesized flag for a source_date range."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _parse_iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_date", type=_parse_iso_date, help="Inclusive start date (YYYY-MM-DD).")
    parser.add_argument("end_date", type=_parse_iso_date, help="Inclusive end date (YYYY-MM-DD).")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show matching rows without updating anything.",
    )
    return parser


def _print_rows(rows: list[dict]) -> None:
    if not rows:
        print("No matching rows found.")
        return

    for row in rows:
        print(
            f"{row['source_date']} | {row['source']} | {row['document_name']} | "
            f"id={row['id']} | synthesized={row['synthesized']}"
        )


def main() -> int:
    args = _build_parser().parse_args()

    if args.start_date > args.end_date:
        print("start_date must be on or before end_date.", file=sys.stderr)
        return 2

    try:
        from src.database import DatabaseClient
    except ImportError as exc:
        print(
            "Failed to import project dependencies. Run this with the project virtualenv, for example: "
            "`.venv/bin/python reset_synthesized_range.py 2026-03-02 2026-03-08`",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    db = DatabaseClient()

    if args.preview:
        rows = db.reset_synthesized_by_source_date(
            args.start_date,
            args.end_date,
            preview_only=True,
        )
        print(
            f"Preview for source_date {args.start_date} through {args.end_date}: {len(rows)} row(s)"
        )
        _print_rows(rows)
        return 0

    rows = db.reset_synthesized_by_source_date(args.start_date, args.end_date)
    print(
        f"Reset synthesized=false for source_date {args.start_date} through {args.end_date}: "
        f"{len(rows)} row(s)"
    )
    _print_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
