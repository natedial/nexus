from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from distill_tool.eval import evaluate_queries, load_judged_queries, summary_to_dict
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
            conn.execute("INSERT INTO keyword_fts (chunk_id, terms) VALUES (?, ?)", (chunk_id, " ".join(k["term"] for k in keywords)))
            for keyword in keywords:
                conn.execute(
                    """
                    INSERT INTO chunk_keywords (chunk_id, term, source, score)
                    VALUES (?, ?, ?, ?)
                    """,
                    (chunk_id, keyword["term"], keyword["source"], keyword["score"]),
                )
        conn.commit()

    import numpy as np

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


def test_load_judged_queries_supports_binary_and_graded_relevance(tmp_path: Path) -> None:
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(
        "\n".join(
            [
                json.dumps({"query_id": "q1", "query": "impact", "relevant": ["c1", "c2"]}),
                json.dumps({"query_id": "q2", "query": "energy", "relevant": {"c3": 2, "c2": 1}}),
            ]
        ),
        encoding="utf-8",
    )

    queries = load_judged_queries(queries_path)

    assert queries[0].relevant_chunk_ids == {"c1": 1.0, "c2": 1.0}
    assert queries[1].relevant_chunk_ids == {"c3": 2.0, "c2": 1.0}


def test_evaluate_queries_reports_recall_mrr_and_ndcg(tmp_path: Path) -> None:
    db_path, npz_path = _build_test_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(
        "\n".join(
            [
                json.dumps({"query_id": "q1", "query": "impact on fiscal deficit", "relevant": {"c1": 2, "c2": 1}}),
                json.dumps({"query_id": "q2", "query": "energy prices", "relevant": ["c3"]}),
            ]
        ),
        encoding="utf-8",
    )

    summary = evaluate_queries(engine, load_judged_queries(queries_path), limit=3, semantic_weight=0.0)

    assert summary.num_queries == 2
    assert 0.0 <= summary.recall_at_k <= 1.0
    assert 0.0 <= summary.mrr_at_k <= 1.0
    assert 0.0 <= summary.ndcg_at_k <= 1.0
    assert summary.query_results[0].retrieved_chunk_ids
    payload = summary_to_dict(summary)
    assert payload["metrics"]["recall_at_k"] >= 0.0
    assert payload["queries"][0]["query_id"] == "q1"
