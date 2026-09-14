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


import hashlib

import numpy as np


def _build_api_test_corpus(tmp_path: Path) -> tuple[str, str]:
    """Build a minimal corpus for API tests. Returns (db_path, npz_path) as strings."""
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        keywords = json.dumps([{"term": "cpi", "source": "dictionary", "score": 1.0}])
        text = "CPI consensus was above expectations in January"
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
            VALUES ('c1', 'r1', 'jan.md', '2025-01-15', 1, 0, ?, ?, ?)
            """,
            (text, keywords, text_hash),
        )
        conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES ('c1', ?)", (text,))
        conn.execute("INSERT INTO keyword_fts (chunk_id, terms) VALUES ('c1', 'cpi')")
        conn.execute(
            "INSERT INTO chunk_keywords (chunk_id, term, source, score) VALUES ('c1', 'cpi', 'dictionary', 1.0)"
        )
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c1"]),
        embeddings=np.array([[0.8, 0.1, 0.1]], dtype="float32"),
    )
    return str(db_path), str(npz_path)


def test_api_search_returns_list_of_dicts(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)
    results = search("CPI consensus", db_path=db_path, npz_path=npz_path, limit=5)

    assert isinstance(results, list)
    assert len(results) >= 1
    result = results[0]
    assert isinstance(result, dict)
    expected_keys = {
        "chunk_id", "source_path", "source_date", "page_number",
        "text", "keywords", "lexical_score", "semantic_score", "hybrid_score",
    }
    assert set(result.keys()) == expected_keys
    assert "run_id" not in result
    assert "chunk_index" not in result


def test_api_search_validates_date_format(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)

    with pytest.raises(ValueError, match="date_from must be ISO format"):
        search("CPI", db_path=db_path, date_from="January 2025")

    with pytest.raises(ValueError, match="date_to must be ISO format"):
        search("CPI", db_path=db_path, date_to="2025/01/31")


def test_api_search_passes_date_filters(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)

    results = search(
        "CPI consensus",
        db_path=db_path,
        npz_path=npz_path,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )
    assert len(results) >= 1

    results = search(
        "CPI consensus",
        db_path=db_path,
        npz_path=npz_path,
        date_from="2025-06-01",
        date_to="2025-06-30",
    )
    assert results == []
