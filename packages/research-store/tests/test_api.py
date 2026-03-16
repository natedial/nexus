from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from distill_tool.storage import init_db


def test_corpus_info_on_empty_database(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    info = corpus_info(str(db_path))

    assert info["total_chunks"] == 0
    assert info["total_runs"] == 0
    assert info["date_range"] is None
    assert info["sources"] == []


def test_corpus_info_returns_correct_aggregates(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        for chunk_id, source_date, source_path in [
            ("c1", "2025-01-15", "jan.md"),
            ("c2", "2025-03-10", "mar.md"),
            ("c3", None, "old.md"),
        ]:
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
                VALUES (?, ?, ?, ?, 1, 0, 'text', '[]', ?)
                """,
                (chunk_id, "r1", source_path, source_date, chunk_id),
            )
        conn.commit()

    info = corpus_info(str(db_path))

    assert info["total_chunks"] == 3
    assert info["total_runs"] == 1
    assert info["date_range"] == {"min": "2025-01-15", "max": "2025-03-10"}
    assert sorted(info["sources"]) == ["jan.md", "mar.md", "old.md"]


def test_corpus_info_null_dates_returns_none_date_range(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
            VALUES ('c1', 'r1', 'x.md', NULL, 1, 0, 'text', '[]', 'h1')
            """
        )
        conn.commit()

    info = corpus_info(str(db_path))

    assert info["date_range"] is None
