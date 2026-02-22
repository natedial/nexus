from __future__ import annotations

import argparse
import os
from pathlib import Path

from distill_tool.chunking import FALLBACK_MIN_CHARS, FALLBACK_TARGET_CHARS, PAGE_MARKER_REGEX
from distill_tool.supabase_indexer import index_pending_documents


def main() -> None:
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
    parser.add_argument("--index-version", type=str, default="v1")
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

    out_dir = Path(args.out_dir)
    db_path = Path(args.db) if args.db else out_dir / "chunks.sqlite"
    npz_path = Path(args.npz) if args.npz else out_dir / "embeddings.npz"

    stats = index_pending_documents(
        supabase_url=args.supabase_url,
        supabase_key=args.supabase_key,
        db_path=db_path,
        npz_path=npz_path,
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
        index_version=args.index_version,
        table=args.table,
        schema=args.schema,
    )

    print(
        "Supabase indexing complete "
        f"(scanned={stats.scanned}, claimed={stats.claimed}, "
        f"indexed={stats.indexed}, failed={stats.failed})"
    )
    print(f"Corpus DB: {db_path}")
    print(f"Embeddings: {npz_path}")


if __name__ == "__main__":
    main()
