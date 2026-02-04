from __future__ import annotations

import argparse
import sys
from pathlib import Path

from distill_tool.chunking import PAGE_MARKER_REGEX
from distill_tool.pipeline import distill_file, distill_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Distill markdown into keywords and embeddings.")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--file", type=str, help="Path to a markdown file.")
    input_group.add_argument("--text", type=str, help="Raw markdown text.")
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
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size.")
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding generation (still writes metadata/keywords).",
    )

    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    db_path = Path(args.db) if args.db else out_dir / "chunks.sqlite"
    npz_path = Path(args.npz) if args.npz else out_dir / "embeddings.npz"

    if args.file:
        result = distill_file(
            file_path=args.file,
            db_path=db_path,
            npz_path=npz_path,
            dictionary_path=args.dictionary,
            model_name=args.model,
            max_keywords=args.max_keywords,
            overlap_paragraphs=args.overlap_paragraphs,
            page_marker_regex=args.page_marker_regex,
            batch_size=args.batch_size,
            skip_embeddings=args.no_embeddings,
        )
    else:
        text = args.text
        if text is None:
            if sys.stdin.isatty():
                parser.error("Provide --file, --text, or pipe markdown via stdin.")
            text = sys.stdin.read()
        result = distill_markdown(
            markdown=text,
            source_path=None,
            db_path=db_path,
            npz_path=npz_path,
            dictionary_path=args.dictionary,
            model_name=args.model,
            max_keywords=args.max_keywords,
            overlap_paragraphs=args.overlap_paragraphs,
            page_marker_regex=args.page_marker_regex,
            batch_size=args.batch_size,
            skip_embeddings=args.no_embeddings,
        )

    print(f"Wrote SQLite metadata to {result.db_path}")
    print(f"Wrote embeddings to {result.embeddings_path}")


if __name__ == "__main__":
    main()
