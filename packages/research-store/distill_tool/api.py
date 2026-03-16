from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from distill_tool.search import HybridSearchEngine, SearchResult

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(value: str | None, name: str) -> None:
    if value is not None and not _ISO_DATE_RE.match(value):
        raise ValueError(f"{name} must be ISO format YYYY-MM-DD, got: {value!r}")


def corpus_info(db_path: str) -> dict:
    """Return metadata about the corpus.

    Returns dict with keys:
        total_chunks, total_runs, date_range (dict with min/max or None),
        sources (list of distinct source_path strings)
    """
    with sqlite3.connect(db_path) as conn:
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        date_row = conn.execute(
            "SELECT MIN(source_date), MAX(source_date) FROM chunks WHERE source_date IS NOT NULL"
        ).fetchone()
        sources = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_path FROM chunks WHERE source_path IS NOT NULL ORDER BY source_path"
            ).fetchall()
        ]
    return {
        "total_chunks": total_chunks,
        "total_runs": total_runs,
        "date_range": {"min": date_row[0], "max": date_row[1]} if date_row[0] else None,
        "sources": sources,
    }


def search(
    query: str,
    *,
    db_path: str,
    npz_path: str | None = None,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    run_id: str | None = None,
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
) -> list[dict]:
    """Search the distilled research corpus.

    Returns list of dicts with keys:
        chunk_id, source_path, source_date, page_number,
        text, keywords, lexical_score, semantic_score, hybrid_score
    """
    _validate_date(date_from, "date_from")
    _validate_date(date_to, "date_to")

    engine = HybridSearchEngine(
        db_path=Path(db_path),
        npz_path=Path(npz_path) if npz_path else None,
    )
    results: list[SearchResult] = engine.search(
        query=query,
        limit=limit,
        run_id=run_id,
        date_from=date_from,
        date_to=date_to,
        keyword_weight=keyword_weight,
        semantic_weight=semantic_weight,
    )
    return [
        {
            "chunk_id": r.chunk_id,
            "source_path": r.source_path,
            "source_date": r.source_date,
            "page_number": r.page_number,
            "text": r.text,
            "keywords": r.keywords,
            "lexical_score": round(r.lexical_score, 6),
            "semantic_score": round(r.semantic_score, 6),
            "hybrid_score": round(r.hybrid_score, 6),
        }
        for r in results
    ]
