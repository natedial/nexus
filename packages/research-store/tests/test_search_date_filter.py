from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from distill_tool.search import HybridSearchEngine


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_dated_corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a corpus with chunks spanning different source_date values, including NULLs."""
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    rows = [
        ("c-jan", "run-1", "jan.md", "2025-01-15", 1, 0, "CPI consensus was above expectations"),
        ("c-feb", "run-1", "feb.md", "2025-02-10", 1, 0, "Fed rate cut expectations shifted lower"),
        ("c-mar", "run-1", "mar.md", "2025-03-05", 1, 0, "Labor market showed signs of softening"),
        ("c-null", "run-1", "old.md", None, 1, 0, "Undated legacy document about inflation"),
    ]

    keywords = [{"term": "test", "source": "dictionary", "score": 1.0}]
    kw_json = json.dumps(keywords)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_date TEXT,
                dictionary_path TEXT,
                params_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_path TEXT,
                source_date TEXT,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                text_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE chunk_keywords (
                chunk_id TEXT NOT NULL,
                term TEXT NOT NULL,
                source TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (chunk_id, term, source)
            )
            """
        )
        conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text)")
        conn.execute("CREATE VIRTUAL TABLE keyword_fts USING fts5(chunk_id UNINDEXED, terms)")
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("run-1", "test", 3, "test", "{}"),
        )
        for chunk_id, run_id, source_path, source_date, page, idx, text in rows:
            text_hash = _hash(text)
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, run_id, source_path, source_date, page, idx, text, kw_json, text_hash),
            )
            conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)", (chunk_id, text))
            conn.execute("INSERT INTO keyword_fts (chunk_id, terms) VALUES (?, ?)", (chunk_id, "test"))
            conn.execute(
                "INSERT INTO chunk_keywords (chunk_id, term, source, score) VALUES (?, ?, ?, ?)",
                (chunk_id, "test", "dictionary", 1.0),
            )
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c-jan", "c-feb", "c-mar", "c-null"]),
        embeddings=np.array(
            [
                [0.8, 0.1, 0.1],
                [0.1, 0.8, 0.1],
                [0.1, 0.1, 0.8],
                [0.5, 0.3, 0.2],
            ],
            dtype="float32",
        ),
    )
    return db_path, npz_path


def test_chunk_ids_for_date_range_returns_none_when_no_filter(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range(None, None)
    assert result is None


def test_chunk_ids_for_date_range_filters_by_date_from(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2025-02-01", None)
    assert result == {"c-feb", "c-mar"}


def test_chunk_ids_for_date_range_filters_by_date_to(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range(None, "2025-02-01")
    assert result == {"c-jan"}


def test_chunk_ids_for_date_range_filters_by_both(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2025-01-01", "2025-01-31")
    assert result == {"c-jan"}


def test_chunk_ids_for_date_range_excludes_null_dates(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2020-01-01", "2030-01-01")
    assert "c-null" not in result
    assert result == {"c-jan", "c-feb", "c-mar"}


def test_chunk_ids_for_date_range_returns_empty_set_for_no_matches(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2099-01-01", "2099-12-31")
    assert result == set()
