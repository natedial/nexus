from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from distill_tool.search import HybridSearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid keyword/syntax/semantic search over distilled corpus.")
    parser.add_argument("--db", type=str, required=True, help="Path to chunks SQLite database.")
    parser.add_argument("--npz", type=str, default=None, help="Path to embeddings npz sidecar.")
    parser.add_argument("--query", type=str, required=True, help="Query text. Supports FTS syntax.")
    parser.add_argument("--limit", type=int, default=10, help="Number of results.")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run_id filter.")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2", help="Embedding model for query vector.")
    parser.add_argument(
        "--keyword-weight",
        type=float,
        default=0.55,
        help="Weight for lexical/keyword score in hybrid rank.",
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=0.45,
        help="Weight for embedding similarity score in hybrid rank.",
    )
    parser.add_argument(
        "--min-lexical-score",
        type=float,
        default=0.05,
        help="Lexical floor; results below this score are demoted (0 disables floor).",
    )
    parser.add_argument(
        "--semantic-tail-mode",
        type=str,
        default="filter",
        choices=["filter", "demote", "allow"],
        help="Handling for semantic-only matches when lexical signal exists.",
    )
    parser.add_argument(
        "--semantic-tail-penalty",
        type=float,
        default=0.25,
        help="Penalty multiplier used when semantic-tail-mode=demote.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON results.",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=240,
        help="Preview character count for text output mode.",
    )
    args = parser.parse_args()

    engine = HybridSearchEngine(
        db_path=Path(args.db),
        npz_path=Path(args.npz) if args.npz else None,
        model_name=args.model,
    )
    results = engine.search(
        query=args.query,
        limit=args.limit,
        run_id=args.run_id,
        keyword_weight=args.keyword_weight,
        semantic_weight=args.semantic_weight,
        min_lexical_score=args.min_lexical_score,
        semantic_tail_mode=args.semantic_tail_mode,
        semantic_tail_penalty=args.semantic_tail_penalty,
    )
    if args.semantic_weight > 0 and engine.last_semantic_error:
        print(
            f"warning: semantic scoring unavailable ({engine.last_semantic_error}); using lexical ranking.",
            file=sys.stderr,
        )

    if args.json:
        payload = [
            {
                "chunk_id": r.chunk_id,
                "run_id": r.run_id,
                "source_path": r.source_path,
                "page_number": r.page_number,
                "chunk_index": r.chunk_index,
                "lexical_score": round(r.lexical_score, 6),
                "semantic_score": round(r.semantic_score, 6),
                "hybrid_score": round(r.hybrid_score, 6),
                "keywords": r.keywords,
                "text": r.text,
            }
            for r in results
        ]
        print(json.dumps(payload, indent=2))
        return

    for idx, result in enumerate(results, start=1):
        preview = " ".join(result.text.split())
        if len(preview) > args.preview_chars:
            preview = preview[: args.preview_chars].rstrip() + "..."
        print(f"{idx}. chunk={result.chunk_id} page={result.page_number} source={result.source_path}")
        print(
            f"   scores: hybrid={result.hybrid_score:.3f} lexical={result.lexical_score:.3f} semantic={result.semantic_score:.3f}"
        )
        print(f"   text: {preview}")


if __name__ == "__main__":
    main()
