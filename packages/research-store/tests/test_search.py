from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from distill_tool.search import HybridSearchEngine


def _build_test_corpus(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    rows = [
        (
            "c1",
            "run-1",
            "sample.md",
            1,
            0,
            "The impact of the fiscal deficit on borrowing costs widened sharply this quarter.",
            [
                {"term": "impact", "source": "dict", "score": 1.0},
                {"term": "fiscal deficit", "source": "dict", "score": 1.0},
            ],
            "impact fiscal deficit borrowing costs",
        ),
        (
            "c2",
            "run-1",
            "sample.md",
            1,
            1,
            "Policy impact was broad and the deficit path is uncertain under current fiscal stance.",
            [
                {"term": "impact", "source": "dict", "score": 1.0},
                {"term": "fiscal", "source": "dict", "score": 0.8},
                {"term": "deficit", "source": "dict", "score": 0.8},
            ],
            "policy impact deficit fiscal stance",
        ),
        (
            "c3",
            "run-1",
            "sample.md",
            2,
            0,
            "Energy prices cooled and labor market conditions remained stable.",
            [{"term": "energy", "source": "dict", "score": 1.0}],
            "energy prices labor market",
        ),
    ]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_path TEXT,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text)")
        conn.execute("CREATE VIRTUAL TABLE keyword_fts USING fts5(chunk_id UNINDEXED, keywords)")
        for chunk_id, run_id, source_path, page_number, chunk_index, text, keywords, keyword_text in rows:
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, page_number, chunk_index, text, keywords_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, run_id, source_path, page_number, chunk_index, text, json.dumps(keywords)),
            )
            conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)", (chunk_id, text))
            conn.execute("INSERT INTO keyword_fts (chunk_id, keywords) VALUES (?, ?)", (chunk_id, keyword_text))
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c1", "c2", "c3"]),
        embeddings=np.array(
            [
                [0.7, 0.2, 0.1],
                [0.6, 0.3, 0.1],
                [0.1, 0.1, 0.8],
            ],
            dtype="float32",
        ),
    )
    return db_path, npz_path


def test_search_skips_semantic_when_weight_zero(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    def _fail_if_called():
        raise AssertionError("_get_model should not be called when semantic_weight=0")

    monkeypatch.setattr(engine, "_get_model", _fail_if_called)
    results = engine.search(query="impact on fiscal deficit", limit=3, keyword_weight=1.0, semantic_weight=0.0)

    assert results
    assert engine.last_semantic_error is None
    assert all(result.semantic_score == 0.0 for result in results)


def test_search_falls_back_to_lexical_when_semantic_fails(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    def _raise_runtime_error():
        raise RuntimeError("offline model unavailable")

    monkeypatch.setattr(engine, "_get_model", _raise_runtime_error)
    results = engine.search(query="impact on fiscal deficit", limit=3)

    assert results
    assert engine.last_semantic_error is not None
    assert "RuntimeError" in engine.last_semantic_error
    assert all(result.semantic_score == 0.0 for result in results)


def test_natural_query_phrase_boosts_exact_phrase_hits(tmp_path: Path) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(query="impact on fiscal deficit", limit=3, semantic_weight=0.0)

    assert results
    assert results[0].chunk_id == "c1"


def test_search_filters_semantic_tail_when_lexical_signal_exists(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    monkeypatch.setattr(engine, "_lexical_scores", lambda query, run_id, limit: {"c1": 0.6, "c2": 0.2})
    monkeypatch.setattr(engine, "_semantic_scores", lambda query, run_id, limit: {"c1": 0.5, "c2": 0.6, "c3": 0.95})
    results = engine.search(query="q", limit=3, keyword_weight=0.5, semantic_weight=0.5)

    chunk_ids = [result.chunk_id for result in results]
    assert "c3" not in chunk_ids
    assert chunk_ids == ["c1", "c2"]


def test_search_can_allow_semantic_tail(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    monkeypatch.setattr(engine, "_lexical_scores", lambda query, run_id, limit: {"c1": 0.6, "c2": 0.2})
    monkeypatch.setattr(engine, "_semantic_scores", lambda query, run_id, limit: {"c1": 0.5, "c2": 0.6, "c3": 0.95})
    results = engine.search(
        query="q",
        limit=3,
        keyword_weight=0.5,
        semantic_weight=0.5,
        min_lexical_score=0.0,
        semantic_tail_mode="allow",
    )

    chunk_ids = [result.chunk_id for result in results]
    assert "c3" in chunk_ids


def test_search_demotes_below_lexical_floor(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    monkeypatch.setattr(engine, "_lexical_scores", lambda query, run_id, limit: {"c1": 0.6, "c2": 0.02})
    monkeypatch.setattr(engine, "_semantic_scores", lambda query, run_id, limit: {})
    results = engine.search(
        query="q",
        limit=2,
        keyword_weight=1.0,
        semantic_weight=0.0,
        min_lexical_score=0.05,
    )

    score_by_id = {result.chunk_id: result.hybrid_score for result in results}
    assert score_by_id["c1"] == 0.6
    assert score_by_id["c2"] < 0.02
