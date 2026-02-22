from __future__ import annotations

import argparse
from pathlib import Path

from distill_tool.storage import backfill_search_indexes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill keyword + FTS indexes for an existing distilled SQLite corpus."
    )
    parser.add_argument("--db", type=str, required=True, help="Path to chunks SQLite database.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Chunk batch size for index writes.",
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Append to existing indexes instead of clearing them first.",
    )
    args = parser.parse_args()

    stats = backfill_search_indexes(
        db_path=Path(args.db),
        batch_size=args.batch_size,
        rebuild=not args.no_rebuild,
    )

    print(f"Indexed chunks: {stats['chunks_indexed']}")
    print(f"Keyword rows written: {stats['keyword_rows_written']}")


if __name__ == "__main__":
    main()
