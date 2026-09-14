from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from distill_tool.chunking import FALLBACK_MIN_CHARS, FALLBACK_TARGET_CHARS, PAGE_MARKER_REGEX
from distill_tool.supabase_indexer import IndexingStats, index_pending_documents


logger = logging.getLogger(__name__)


def run_indexing_worker(
    args: argparse.Namespace,
    *,
    index_once=None,
    sleep_fn=time.sleep,
    log: logging.Logger | None = None,
) -> IndexingStats:
    active_logger = log or logger
    index_once = index_once or index_pending_documents
    total = IndexingStats(scanned=0, claimed=0, indexed=0, failed=0, reclaimed=0)
    cycle = 0

    while True:
        cycle += 1
        try:
            stats = index_once(
                supabase_url=args.supabase_url,
                supabase_key=args.supabase_key,
                db_path=args.db_path,
                npz_path=args.npz_path,
                dictionary_path=args.dictionary,
                model_name=args.model,
                max_keywords=args.max_keywords,
                overlap_paragraphs=args.overlap_paragraphs,
                page_marker_regex=args.page_marker_regex,
                fallback_target_chars=args.fallback_target_chars,
                fallback_min_chars=args.fallback_min_chars,
                batch_size=args.batch_size,
                skip_embeddings=args.no_embeddings,
                poll_limit=args.poll_limit,
                stale_processing_seconds=args.stale_processing_seconds,
                index_version=args.index_version,
                table=args.table,
                schema=args.schema,
            )
            total = total + stats
            active_logger.info(
                "indexing cycle %s complete (scanned=%s claimed=%s indexed=%s failed=%s reclaimed=%s)",
                cycle,
                stats.scanned,
                stats.claimed,
                stats.indexed,
                stats.failed,
                stats.reclaimed,
            )
        except KeyboardInterrupt:
            active_logger.info("indexing worker interrupted after %s cycle(s)", cycle - 1)
            break
        except Exception:
            if not args.continuous:
                raise
            active_logger.exception(
                "indexing cycle %s failed; retrying in %.1f seconds",
                cycle,
                args.error_backoff_seconds,
            )
            sleep_fn(args.error_backoff_seconds)
            if args.max_cycles is not None and cycle >= args.max_cycles:
                break
            continue

        if not args.continuous:
            break
        if args.max_cycles is not None and cycle >= args.max_cycles:
            break

        sleep_fn(args.poll_interval_seconds)

    return total


def main() -> None:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument(
        "--env-file",
        type=str,
        default=".env",
        help=argparse.SUPPRESS,
    )
    bootstrap_args, _ = bootstrap.parse_known_args()
    load_dotenv(dotenv_path=bootstrap_args.env_file)

    parser = argparse.ArgumentParser(
        description=(
            "Index pending parsed_research rows from Supabase by distilling "
            "parsed_data.full_text into local chunks + embeddings."
        )
    )
    parser.add_argument("--supabase-url", type=str, default=os.getenv("SUPABASE_URL"))
    parser.add_argument("--supabase-key", type=str, default=os.getenv("SUPABASE_KEY"))
    parser.add_argument("--table", type=str, default="parsed_research")
    parser.add_argument("--schema", type=str, default="public")
    parser.add_argument("--poll-limit", type=int, default=25)
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Keep polling for more work until interrupted.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=30.0,
        help="Sleep interval between successful polling cycles in continuous mode.",
    )
    parser.add_argument(
        "--error-backoff-seconds",
        type=float,
        default=60.0,
        help="Sleep interval after a failed cycle in continuous mode.",
    )
    parser.add_argument(
        "--stale-processing-seconds",
        type=float,
        default=3600.0,
        help="Reclaim rows stuck in processing longer than this many seconds; use 0 to disable.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--index-version", type=str, default="v1")
    parser.add_argument(
        "--env-file",
        type=str,
        default=".env",
        help="Path to dotenv file loaded before reading SUPABASE_URL/SUPABASE_KEY.",
    )
    parser.add_argument("--dict", dest="dictionary", type=str, help="Path to dictionary file.")
    parser.add_argument("--out-dir", type=str, default="distill_out", help="Output directory.")
    parser.add_argument("--db", type=str, help="SQLite database path.")
    parser.add_argument("--npz", type=str, help="Embeddings npz path.")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2", help="Embedding model name.")
    parser.add_argument("--max-keywords", type=int, default=20, help="Max keywords per chunk.")
    parser.add_argument(
        "--overlap-paragraphs",
        type=int,
        default=1,
        help="Paragraphs of overlap between pages.",
    )
    parser.add_argument(
        "--page-marker-regex",
        type=str,
        default=None,
        help=f"Regex to split pages (defaults to '{PAGE_MARKER_REGEX}').",
    )
    parser.add_argument(
        "--fallback-target-chars",
        type=int,
        default=FALLBACK_TARGET_CHARS,
        help="Fallback chunk target size in characters when no page markers are found.",
    )
    parser.add_argument(
        "--fallback-min-chars",
        type=int,
        default=FALLBACK_MIN_CHARS,
        help="Minimum chunk size before splitting in fallback paragraph chunking.",
    )
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size.")
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding generation (still writes metadata/keywords).",
    )
    args = parser.parse_args()

    if not args.supabase_url:
        parser.error("Missing Supabase URL. Use --supabase-url or set SUPABASE_URL.")
    if not args.supabase_key:
        parser.error("Missing Supabase key. Use --supabase-key or set SUPABASE_KEY.")
    if args.poll_limit < 1:
        parser.error("--poll-limit must be at least 1.")
    if args.continuous and args.poll_interval_seconds < 0:
        parser.error("--poll-interval-seconds must be >= 0.")
    if args.continuous and args.error_backoff_seconds < 0:
        parser.error("--error-backoff-seconds must be >= 0.")
    if args.stale_processing_seconds < 0:
        parser.error("--stale-processing-seconds must be >= 0.")

    out_dir = Path(args.out_dir)
    args.db_path = Path(args.db) if args.db else out_dir / "chunks.sqlite"
    args.npz_path = Path(args.npz) if args.npz else out_dir / "embeddings.npz"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    stats = run_indexing_worker(args)

    print(
        "Supabase indexing complete "
        f"(scanned={stats.scanned}, claimed={stats.claimed}, "
        f"indexed={stats.indexed}, failed={stats.failed}, reclaimed={stats.reclaimed})"
    )
    print(f"Corpus DB: {args.db_path}")
    print(f"Embeddings: {args.npz_path}")


if __name__ == "__main__":
    main()
