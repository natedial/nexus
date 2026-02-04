from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    model_name: str
    embedding_dim: int
    source: str
    dictionary_path: str | None
    params: dict


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    run_id: str
    source_path: str | None
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


def store_run(db_path: str | Path, run_info: RunInfo) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, model_name, embedding_dim, source, dictionary_path, params_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_info.run_id,
                run_info.model_name,
                run_info.embedding_dim,
                run_info.source,
                run_info.dictionary_path,
                json.dumps(run_info.params),
            ),
        )


def store_chunks(db_path: str | Path, chunks: Iterable[ChunkRecord]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO chunks (
                chunk_id, run_id, source_path, page_number, chunk_index,
                text, keywords_json, text_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk.chunk_id,
                    chunk.run_id,
                    chunk.source_path,
                    chunk.page_number,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.keywords_json,
                    chunk.text_hash,
                )
                for chunk in chunks
            ],
        )


def save_embeddings(npz_path: str | Path, chunk_ids: list[str], embeddings: np.ndarray) -> None:
    npz_path = Path(npz_path)
    npz_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, chunk_ids=np.array(chunk_ids), embeddings=embeddings)
