from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from distill_tool.search import HybridSearchEngine


def _build_test_corpus(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    duplicate_text = "The impact of the fiscal deficit on borrowing costs widened sharply this quarter."
    rows = [
        (
            "c1",
            "run-1",
            "sample.md",
            1,
            0,
            duplicate_text,
            [
                {"term": "impact", "source": "dictionary", "score": 1.0},
                {"term": "fiscal deficit", "source": "dictionary", "score": 2.0},
            ],
        ),
        (
            "c2",
            "run-1",
            "sample.md",
            1,
            1,
            "Policy impact was broad and the deficit path is uncertain under current fiscal stance.",
            [
                {"term": "impact", "source": "dictionary", "score": 1.0},
                {"term": "fiscal", "source": "dictionary", "score": 0.8},
                {"term": "deficit", "source": "dictionary", "score": 0.8},
            ],
        ),
        (
            "c3",
            "run-1",
            "sample.md",
            2,
            0,
            "Energy prices cooled and labor market conditions remained stable.",
            [{"term": "energy", "source": "dictionary", "score": 1.0}],
        ),
        (
            "c4",
            "run-2",
            "other.md",
            4,
            0,
            duplicate_text,
            [
                {"term": "impact", "source": "dictionary", "score": 1.0},
                {"term": "fiscal deficit", "source": "dictionary", "score": 2.0},
            ],
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
        for chunk_id, run_id, source_path, page_number, chunk_index, text, keywords in rows:
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, page_number, chunk_index, text, keywords_json, text_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, run_id, source_path, page_number, chunk_index, text, json.dumps(keywords), text_hash),
            )
            conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)", (chunk_id, text))
            conn.execute(
                "INSERT INTO keyword_fts (chunk_id, terms) VALUES (?, ?)",
                (chunk_id, " ".join(keyword["term"] for keyword in keywords)),
            )
            for keyword in keywords:
                conn.execute(
                    """
                    INSERT INTO chunk_keywords (chunk_id, term, source, score)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chunk_id, keyword["term"], keyword["source"], keyword["score"]),
                )
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c1", "c2", "c3", "c4"]),
        embeddings=np.array(
            [
                [0.7, 0.2, 0.1],
                [0.6, 0.3, 0.1],
                [0.1, 0.1, 0.8],
                [0.7, 0.2, 0.1],
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


def test_keyword_scoring_prefers_exact_dictionary_phrase(tmp_path: Path) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(query="impact on fiscal deficit", limit=3, semantic_weight=0.0)

    assert results
    assert results[0].chunk_id in {"c1", "c4"}
    assert all(result.chunk_id != "c2" for result in results[:1])


def test_search_filters_semantic_tail_when_lexical_signal_exists(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    monkeypatch.setattr(engine, "_lexical_scores", lambda query, run_id, limit: {"c1": 0.6, "c2": 0.2})
    monkeypatch.setattr(engine, "_semantic_scores", lambda query, run_id, limit: {"c1": 0.5, "c2": 0.6, "c3": 0.95})
    monkeypatch.setattr(engine, "_load_text_hash_counts", lambda text_hashes: {text_hash: 1 for text_hash in text_hashes})
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
    assert score_by_id["c1"] > score_by_id["c2"]


def test_search_deduplicates_identical_chunks(tmp_path: Path) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(query="impact on fiscal deficit", limit=4, semantic_weight=0.0)

    chunk_ids = [result.chunk_id for result in results]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert len({"c1", "c4"} & set(chunk_ids)) == 1
