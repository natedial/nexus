from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from distill_tool.storage import backfill_search_indexes, init_db


def test_backfill_search_indexes_normalizes_keyword_terms(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs (run_id, model_name, embedding_dim, source, dictionary_path, params_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "model", 0, "inline", None, "{}"),
        )
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, run_id, source_path, page_number, chunk_index, text, keywords_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "c1",
                "run-1",
                "sample.md",
                1,
                0,
                "The FCA oversees conduct.",
                json.dumps(
                    [
                        {"term": "Financial Conduct Authority", "source": "dictionary", "score": 2.0},
                        {"term": "FCA", "source": "dictionary", "score": 1.0},
                    ]
                ),
                "hash-1",
            ),
        )
        conn.commit()

    stats = backfill_search_indexes(db_path=db_path)

    assert stats["chunks_indexed"] == 1
    assert stats["keyword_rows_written"] == 2

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT term FROM chunk_keywords ORDER BY term"
        ).fetchall()
        keyword_fts_row = conn.execute("SELECT terms FROM keyword_fts WHERE chunk_id = ?", ("c1",)).fetchone()

    assert [row[0] for row in rows] == ["fca", "financial conduct authority"]
    assert keyword_fts_row is not None
    assert "financial conduct authority" in keyword_fts_row[0]
