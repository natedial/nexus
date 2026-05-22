from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from distill_tool.storage import (
    ChunkRecord,
    RunInfo,
    backfill_search_indexes,
    init_db,
    store_chunks,
    store_run,
)


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


def test_init_db_adds_source_date_columns_to_existing_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now')),
                model_name TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                source TEXT NOT NULL,
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
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        chunk_columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}

    assert "source_date" in run_columns
    assert "source_date" in chunk_columns


def test_init_db_creates_source_date_index(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(chunks)").fetchall()
        }

    assert "idx_chunks_source_date" in indexes


def test_store_chunks_replaces_stale_chunks_for_same_source_path(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)
    store_run(
        db_path,
        RunInfo(
            run_id="run-1",
            model_name="model",
            embedding_dim=0,
            source="supabase:7",
            source_date="2026-05-01",
            dictionary_path=None,
            params={},
        ),
    )
    store_chunks(
        db_path,
        [
            ChunkRecord(
                chunk_id="old-1",
                run_id="run-1",
                source_path="supabase:7",
                source_date="2026-05-01",
                page_number=1,
                chunk_index=0,
                text="Old body",
                keywords_json=json.dumps(
                    [{"term": "old", "source": "auto", "score": 1.0}]
                ),
                text_hash="old-hash",
            ),
            ChunkRecord(
                chunk_id="other-1",
                run_id="run-1",
                source_path="supabase:8",
                source_date="2026-05-01",
                page_number=1,
                chunk_index=0,
                text="Other body",
                keywords_json="[]",
                text_hash="other-hash",
            ),
        ],
    )

    store_run(
        db_path,
        RunInfo(
            run_id="run-2",
            model_name="model",
            embedding_dim=0,
            source="supabase:7",
            source_date="2026-05-01",
            dictionary_path=None,
            params={},
        ),
    )
    store_chunks(
        db_path,
        [
            ChunkRecord(
                chunk_id="new-1",
                run_id="run-2",
                source_path="supabase:7",
                source_date="2026-05-01",
                page_number=1,
                chunk_index=0,
                text="New body",
                keywords_json=json.dumps(
                    [{"term": "new", "source": "auto", "score": 1.0}]
                ),
                text_hash="new-hash",
            )
        ],
    )

    with sqlite3.connect(db_path) as conn:
        chunks = conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id").fetchall()
        keyword_rows = conn.execute(
            "SELECT chunk_id, term FROM chunk_keywords ORDER BY chunk_id, term"
        ).fetchall()
        fts_rows = conn.execute("SELECT chunk_id FROM chunks_fts ORDER BY chunk_id").fetchall()

    assert [row[0] for row in chunks] == ["new-1", "other-1"]
    assert keyword_rows == [("new-1", "new")]
    assert [row[0] for row in fts_rows] == ["new-1", "other-1"]
