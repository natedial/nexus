from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from distill_tool.keywords import normalize_term


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    model_name: str
    embedding_dim: int
    source: str
    source_date: str | None
    dictionary_path: str | None
    params: dict


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    run_id: str
    source_path: str | None
    source_date: str | None
    page_number: int
    chunk_index: int
    text: str
    keywords_json: str
    text_hash: str


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now')),
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
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_path TEXT,
                source_date TEXT,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunk_keywords (
                chunk_id TEXT NOT NULL,
                term TEXT NOT NULL,
                source TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (chunk_id, term, source),
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunk_keywords_term
            ON chunk_keywords(term)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunk_keywords_chunk_id
            ON chunk_keywords(chunk_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_text_hash
            ON chunks(text_hash)
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
            USING fts5(chunk_id UNINDEXED, text, tokenize='unicode61')
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS keyword_fts
            USING fts5(chunk_id UNINDEXED, terms, tokenize='unicode61')
            """
        )
        _ensure_column(conn, table="runs", column="source_date", ddl="TEXT")
        _ensure_column(conn, table="chunks", column="source_date", ddl="TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_source_date
            ON chunks(source_date)
            """
        )


def store_run(db_path: str | Path, run_info: RunInfo) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, model_name, embedding_dim, source, source_date, dictionary_path, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_info.run_id,
                run_info.model_name,
                run_info.embedding_dim,
                run_info.source,
                run_info.source_date,
                run_info.dictionary_path,
                json.dumps(run_info.params),
            ),
        )


def store_chunks(db_path: str | Path, chunks: Iterable[ChunkRecord]) -> None:
    chunk_list = list(chunks)
    chunk_ids = [chunk.chunk_id for chunk in chunk_list]

    with sqlite3.connect(db_path) as conn:
        stale_chunk_ids: list[str] = []
        incoming_by_source: dict[str, set[str]] = {}
        for chunk in chunk_list:
            if chunk.source_path:
                incoming_by_source.setdefault(chunk.source_path, set()).add(chunk.chunk_id)

        for source_path, incoming_ids in incoming_by_source.items():
            placeholders = ",".join("?" for _ in incoming_ids)
            rows = conn.execute(
                f"""
                SELECT chunk_id FROM chunks
                WHERE source_path = ?
                  AND chunk_id NOT IN ({placeholders})
                """,
                [source_path, *incoming_ids],
            ).fetchall()
            stale_chunk_ids.extend(str(row[0]) for row in rows)

        conn.executemany(
            """
            INSERT OR REPLACE INTO chunks (
                chunk_id, run_id, source_path, source_date, page_number, chunk_index,
                text, keywords_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.run_id,
                    chunk.source_path,
                    chunk.source_date,
                    chunk.page_number,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.keywords_json,
                    chunk.text_hash,
                )
                for chunk in chunk_list
            ],
        )
        if not chunk_ids:
            return

        cleanup_ids = [*chunk_ids, *stale_chunk_ids]
        placeholders = ",".join("?" for _ in cleanup_ids)
        conn.execute(
            f"DELETE FROM chunk_keywords WHERE chunk_id IN ({placeholders})",
            cleanup_ids,
        )
        conn.execute(
            f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})",
            cleanup_ids,
        )
        conn.execute(
            f"DELETE FROM keyword_fts WHERE chunk_id IN ({placeholders})",
            cleanup_ids,
        )
        if stale_chunk_ids:
            stale_placeholders = ",".join("?" for _ in stale_chunk_ids)
            conn.execute(
                f"DELETE FROM chunks WHERE chunk_id IN ({stale_placeholders})",
                stale_chunk_ids,
            )

        keyword_rows: list[tuple[str, str, str, float]] = []
        keyword_fts_rows: list[tuple[str, str]] = []
        text_fts_rows: list[tuple[str, str]] = []

        for chunk in chunk_list:
            parsed = json.loads(chunk.keywords_json)
            terms_for_fts: list[str] = []
            for item in parsed:
                term = normalize_term(str(item.get("term", "")))
                source = str(item.get("source", "")).strip()
                try:
                    score = float(item.get("score", 0.0))
                except (TypeError, ValueError):
                    score = 0.0
                if not term or not source:
                    continue
                keyword_rows.append((chunk.chunk_id, term, source, score))
                terms_for_fts.append(term)

            text_fts_rows.append((chunk.chunk_id, chunk.text))
            keyword_fts_rows.append((chunk.chunk_id, " ".join(terms_for_fts)))

        if keyword_rows:
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunk_keywords (chunk_id, term, source, score)
                VALUES (?, ?, ?, ?)
                """,
                keyword_rows,
            )
        conn.executemany(
            """
            INSERT INTO chunks_fts (chunk_id, text)
            VALUES (?, ?)
            """,
            text_fts_rows,
        )
        conn.executemany(
            """
            INSERT INTO keyword_fts (chunk_id, terms)
            VALUES (?, ?)
            """,
            keyword_fts_rows,
        )


def _ensure_column(conn: sqlite3.Connection, *, table: str, column: str, ddl: str) -> None:
    existing = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def save_embeddings(npz_path: str | Path, chunk_ids: list[str], embeddings: np.ndarray) -> None:
    npz_path = Path(npz_path)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, chunk_ids=np.array(chunk_ids), embeddings=embeddings)


def backfill_search_indexes(
    db_path: str | Path,
    batch_size: int = 1000,
    rebuild: bool = True,
) -> dict[str, int]:
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")

    init_db(db_path)
    db_path = Path(db_path)

    total_chunks = 0
    total_keywords = 0
    last_rowid = 0

    with sqlite3.connect(db_path) as conn:
        if rebuild:
            conn.execute("DELETE FROM chunk_keywords")
            conn.execute("DELETE FROM chunks_fts")
            conn.execute("DELETE FROM keyword_fts")

        while True:
            rows = conn.execute(
                """
                SELECT rowid, chunk_id, text, keywords_json
                FROM chunks
                WHERE rowid > ?
                ORDER BY rowid
                LIMIT ?
                """,
                (last_rowid, batch_size),
            ).fetchall()
            if not rows:
                break

            keyword_rows: list[tuple[str, str, str, float]] = []
            text_fts_rows: list[tuple[str, str]] = []
            keyword_fts_rows: list[tuple[str, str]] = []

            for rowid, chunk_id, text, keywords_json in rows:
                last_rowid = int(rowid)
                total_chunks += 1
                terms_for_fts: list[str] = []

                try:
                    parsed_keywords = json.loads(keywords_json)
                except json.JSONDecodeError:
                    parsed_keywords = []

                for item in parsed_keywords:
                    term = normalize_term(str(item.get("term", "")))
                    source = str(item.get("source", "")).strip()
                    try:
                        score = float(item.get("score", 0.0))
                    except (TypeError, ValueError):
                        score = 0.0
                    if not term or not source:
                        continue
                    keyword_rows.append((str(chunk_id), term, source, score))
                    terms_for_fts.append(term)

                total_keywords += len(terms_for_fts)
                text_fts_rows.append((str(chunk_id), str(text)))
                keyword_fts_rows.append((str(chunk_id), " ".join(terms_for_fts)))

            if keyword_rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO chunk_keywords (chunk_id, term, source, score)
                    VALUES (?, ?, ?, ?)
                    """,
                    keyword_rows,
                )
            conn.executemany(
                """
                INSERT INTO chunks_fts (chunk_id, text)
                VALUES (?, ?)
                """,
                text_fts_rows,
            )
            conn.executemany(
                """
                INSERT INTO keyword_fts (chunk_id, terms)
                VALUES (?, ?)
                """,
                keyword_fts_rows,
            )
            conn.commit()

    return {
        "chunks_indexed": total_chunks,
        "keyword_rows_written": total_keywords,
    }
