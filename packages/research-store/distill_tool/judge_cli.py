from __future__ import annotations

import argparse
import json
from pathlib import Path

from distill_tool.search import HybridSearchEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a human-readable judging worksheet for a search query.")
    parser.add_argument("--db", type=str, required=True, help="Path to chunks SQLite database.")
    parser.add_argument("--npz", type=str, default=None, help="Path to embeddings npz sidecar.")
    parser.add_argument("--query", type=str, required=True, help="Query text to judge.")
    parser.add_argument("--query-id", type=str, default="q-new", help="Suggested query_id for the judged set entry.")
    parser.add_argument("--limit", type=int, default=10, help="Number of candidates to include.")
    parser.add_argument("--run-id", type=str, default=None, help="Optional run_id filter.")
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
    parser.add_argument("--preview-chars", type=int, default=220, help="Preview character count per result.")
    parser.add_argument("--output", type=str, default=None, help="Optional markdown file to write.")
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

    worksheet = render_worksheet(
        query_id=args.query_id,
        query=args.query,
        results=results,
        preview_chars=args.preview_chars,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(worksheet, encoding="utf-8")

    print(worksheet)


def render_worksheet(
    *,
    query_id: str,
    query: str,
    results: list,
    preview_chars: int,
) -> str:
    template = {
        "query_id": query_id,
        "query": query,
        "relevant": {
            result.chunk_id: 1 for result in results[: min(3, len(results))]
        },
    }

    lines = [
        f"# Judging Worksheet: {query_id}",
        "",
        f"Query: {query}",
        "",
        "Copy this starter JSONL line into `eval/queries.jsonl` and edit the grades:",
        "",
        "```json",
        json.dumps(template, separators=(",", ":")),
        "```",
        "",
        "Grade guide: `1 = relevant`, `2 = very relevant`, `3 = exact hit`",
        "",
        "## Candidates",
        "",
    ]

    for idx, result in enumerate(results, start=1):
        preview = " ".join(result.text.split())
        if len(preview) > preview_chars:
            preview = preview[:preview_chars].rstrip() + "..."
        lines.extend(
            [
                f"{idx}. `chunk_id`: `{result.chunk_id}`",
                f"   `source`: `{result.source_path}` `page`: `{result.page_number}` `chunk_index`: `{result.chunk_index}`",
                f"   `scores`: hybrid={result.hybrid_score:.3f} lexical={result.lexical_score:.3f} semantic={result.semantic_score:.3f}",
                f"   `preview`: {preview}",
                "",
            ]
        )

    if not results:
        lines.append("No candidates returned for this query.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    main()
