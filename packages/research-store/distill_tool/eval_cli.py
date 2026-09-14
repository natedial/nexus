from __future__ import annotations

import argparse
import json
from pathlib import Path

from distill_tool.eval import evaluate_queries, load_judged_queries, summary_to_dict
from distill_tool.search import HybridSearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate hybrid retrieval on a judged query set.")
    parser.add_argument("--db", type=str, required=True, help="Path to chunks SQLite database.")
    parser.add_argument("--npz", type=str, default=None, help="Path to embeddings npz sidecar.")
    parser.add_argument("--queries", type=str, required=True, help="Path to judged queries JSONL file.")
    parser.add_argument("--limit", type=int, default=10, help="Top-k cutoff for evaluation.")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2", help="Embedding model for query vector.")
    parser.add_argument("--keyword-weight", type=float, default=0.55, help="Weight for lexical/keyword score.")
    parser.add_argument("--semantic-weight", type=float, default=0.45, help="Weight for semantic score.")
    parser.add_argument("--min-lexical-score", type=float, default=0.05, help="Lexical floor.")
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
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args()

    engine = HybridSearchEngine(
        db_path=Path(args.db),
        npz_path=Path(args.npz) if args.npz else None,
        model_name=args.model,
    )
    judged_queries = load_judged_queries(Path(args.queries))
    summary = evaluate_queries(
        engine,
        judged_queries,
        limit=args.limit,
        keyword_weight=args.keyword_weight,
        semantic_weight=args.semantic_weight,
        min_lexical_score=args.min_lexical_score,
        semantic_tail_mode=args.semantic_tail_mode,
        semantic_tail_penalty=args.semantic_tail_penalty,
    )

    if args.json:
        print(json.dumps(summary_to_dict(summary), indent=2))
        return

    print(f"Queries: {summary.num_queries}")
    print(f"Cutoff: {summary.limit}")
    print(f"Recall@{summary.limit}: {summary.recall_at_k:.3f}")
    print(f"MRR@{summary.limit}: {summary.mrr_at_k:.3f}")
    print(f"nDCG@{summary.limit}: {summary.ndcg_at_k:.3f}")
    print("")
    for item in summary.query_results:
        print(
            f"{item.query_id}: recall={item.recall_at_k:.3f} mrr={item.mrr_at_k:.3f} "
            f"ndcg={item.ndcg_at_k:.3f} query={item.query}"
        )


if __name__ == "__main__":
    main()
