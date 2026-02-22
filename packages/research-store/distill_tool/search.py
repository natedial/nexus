from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from distill_tool.embeddings import EmbeddingConfig, EmbeddingModel


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    run_id: str
    source_path: str | None
    page_number: int
    chunk_index: int
    text: str
    keywords: list[dict]
    lexical_score: float
    semantic_score: float
    hybrid_score: float


class HybridSearchEngine:
    def __init__(
        self,
        db_path: str | Path,
        npz_path: str | Path | None = None,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.db_path = Path(db_path)
        self.npz_path = Path(npz_path) if npz_path else None
        self.model_name = model_name
        self._model: EmbeddingModel | None = None
        self._embedding_chunk_ids: np.ndarray | None = None
        self._embedding_matrix: np.ndarray | None = None
        self._last_semantic_error: str | None = None
        self._load_embeddings()

    def search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        keyword_weight: float = 0.55,
        semantic_weight: float = 0.45,
        min_lexical_score: float = 0.05,
        semantic_tail_mode: str = "filter",
        semantic_tail_penalty: float = 0.25,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query or limit <= 0:
            return []

        self._last_semantic_error = None
        candidate_limit = max(limit * 8, 50)

        lexical_scores: dict[str, float] = {}
        if keyword_weight > 0.0 or semantic_weight <= 0.0:
            lexical_scores = self._lexical_scores(query, run_id=run_id, limit=candidate_limit)

        semantic_scores: dict[str, float] = {}
        if semantic_weight > 0.0:
            semantic_scores = self._semantic_scores(query, run_id=run_id, limit=candidate_limit)

        if semantic_weight > 0.0 and not semantic_scores:
            if not lexical_scores:
                lexical_scores = self._lexical_scores(query, run_id=run_id, limit=candidate_limit)
            semantic_weight = 0.0
            keyword_weight = 1.0
        elif lexical_scores and not semantic_scores:
            semantic_weight = 0.0
            keyword_weight = 1.0
        elif semantic_scores and not lexical_scores:
            semantic_weight = 1.0
            keyword_weight = 0.0

        total_weight = keyword_weight + semantic_weight
        if total_weight <= 0:
            keyword_weight = 1.0
            semantic_weight = 0.0
            total_weight = 1.0
        keyword_weight /= total_weight
        semantic_weight /= total_weight

        all_chunk_ids = set(lexical_scores) | set(semantic_scores)
        if not all_chunk_ids:
            return []

        min_lexical_score = max(0.0, min_lexical_score)
        semantic_tail_penalty = max(0.0, min(1.0, semantic_tail_penalty))
        semantic_tail_mode = semantic_tail_mode.lower().strip()
        if semantic_tail_mode not in {"filter", "demote", "allow"}:
            semantic_tail_mode = "filter"
        lexical_constraints_active = keyword_weight > 0.0 and any(score > 0.0 for score in lexical_scores.values())

        final_scores: list[tuple[str, float, float, float]] = []
        for chunk_id in all_chunk_ids:
            lexical = lexical_scores.get(chunk_id, 0.0)
            semantic = semantic_scores.get(chunk_id, 0.0)
            hybrid = (keyword_weight * lexical) + (semantic_weight * semantic)

            if lexical_constraints_active and semantic > 0.0 and lexical <= 0.0:
                if semantic_tail_mode == "filter":
                    continue
                if semantic_tail_mode == "demote":
                    hybrid *= semantic_tail_penalty

            if lexical_constraints_active and min_lexical_score > 0.0 and 0.0 <= lexical < min_lexical_score:
                hybrid *= lexical / min_lexical_score

            final_scores.append((chunk_id, lexical, semantic, hybrid))

        final_scores.sort(key=lambda row: row[3], reverse=True)
        top = final_scores[:limit]
        metadata = self._load_chunk_metadata([row[0] for row in top])

        results: list[SearchResult] = []
        for chunk_id, lexical, semantic, hybrid in top:
            chunk = metadata.get(chunk_id)
            if not chunk:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    run_id=chunk["run_id"],
                    source_path=chunk["source_path"],
                    page_number=chunk["page_number"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    keywords=chunk["keywords"],
                    lexical_score=lexical,
                    semantic_score=semantic,
                    hybrid_score=hybrid,
                )
            )

        return results

    def _lexical_scores(self, query: str, run_id: str | None, limit: int) -> dict[str, float]:
        text_query, keyword_query, phrase_query = self._build_lexical_queries(query)
        text_rows = self._fts_query(
            table="chunks_fts",
            query=text_query,
            run_id=run_id,
            limit=limit,
        )
        keyword_rows = self._fts_query(
            table="keyword_fts",
            query=keyword_query,
            run_id=run_id,
            limit=limit,
        )
        phrase_rows: list[tuple[str, float]] = []
        if phrase_query:
            phrase_rows = self._fts_query(
                table="chunks_fts",
                query=phrase_query,
                run_id=run_id,
                limit=limit,
            )

        text_scores = _normalize_bm25(text_rows)
        keyword_scores = _normalize_bm25(keyword_rows)
        phrase_scores = _normalize_bm25(phrase_rows)
        chunk_ids = set(text_scores) | set(keyword_scores) | set(phrase_scores)

        combined: dict[str, float] = {}
        for chunk_id in chunk_ids:
            if phrase_query:
                # Natural-language queries benefit from giving phrase matches extra lift.
                score = (
                    0.50 * keyword_scores.get(chunk_id, 0.0)
                    + 0.30 * text_scores.get(chunk_id, 0.0)
                    + 0.20 * phrase_scores.get(chunk_id, 0.0)
                )
            else:
                # Favor explicit keyword hits while still considering full-text syntax matches.
                score = 0.65 * keyword_scores.get(chunk_id, 0.0) + 0.35 * text_scores.get(chunk_id, 0.0)
            if score > 0.0:
                combined[chunk_id] = score
        return combined

    def _fts_query(
        self,
        table: str,
        query: str,
        run_id: str | None,
        limit: int,
    ) -> list[tuple[str, float]]:
        if not query.strip():
            return []

        sql = (
            f"SELECT {table}.chunk_id, bm25({table}) AS score "
            f"FROM {table} "
            f"JOIN chunks c ON c.chunk_id = {table}.chunk_id "
            f"WHERE {table} MATCH ?"
        )
        params: list[object] = [query]
        if run_id:
            sql += " AND c.run_id = ?"
            params.append(run_id)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                safe_query = _sanitize_fts_query(query)
                if not safe_query:
                    return []
                params[0] = safe_query
                rows = conn.execute(sql, params).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]

    def _semantic_scores(self, query: str, run_id: str | None, limit: int) -> dict[str, float]:
        if self._embedding_matrix is None or self._embedding_chunk_ids is None:
            return {}
        if self._embedding_matrix.size == 0:
            return {}

        try:
            model = self._get_model()
            query_vector = model.embed([query])[0]
            similarities = self._embedding_matrix @ query_vector
        except Exception as exc:  # pragma: no cover - runtime integration path
            message = " ".join(str(exc).split())
            self._last_semantic_error = f"{type(exc).__name__}: {message[:180]}"
            return {}

        if run_id:
            allowed_ids = self._chunk_ids_for_run(run_id)
            if not allowed_ids:
                return {}
            mask = np.array([chunk_id in allowed_ids for chunk_id in self._embedding_chunk_ids], dtype=bool)
            if not np.any(mask):
                return {}
            idxs = np.where(mask)[0]
            subset_scores = similarities[idxs]
            top_n = min(limit, subset_scores.shape[0])
            top_local = np.argpartition(subset_scores, -top_n)[-top_n:]
            top_idxs = idxs[top_local]
        else:
            top_n = min(limit, similarities.shape[0])
            top_idxs = np.argpartition(similarities, -top_n)[-top_n:]

        top_pairs = sorted(
            ((int(i), float(similarities[i])) for i in top_idxs),
            key=lambda row: row[1],
            reverse=True,
        )
        # Dot-product for normalized vectors is cosine in [-1, 1].
        return {
            str(self._embedding_chunk_ids[i]): max(0.0, min(1.0, (score + 1.0) / 2.0))
            for i, score in top_pairs
        }

    @property
    def last_semantic_error(self) -> str | None:
        return self._last_semantic_error

    def _load_chunk_metadata(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, run_id, source_path, page_number, chunk_index, text, keywords_json
                FROM chunks
                WHERE chunk_id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()

        metadata: dict[str, dict] = {}
        for row in rows:
            metadata[str(row[0])] = {
                "run_id": str(row[1]),
                "source_path": row[2],
                "page_number": int(row[3]),
                "chunk_index": int(row[4]),
                "text": str(row[5]),
                "keywords": json.loads(row[6]),
            }
        return metadata

    def _chunk_ids_for_run(self, run_id: str) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT chunk_id FROM chunks WHERE run_id = ?", (run_id,)).fetchall()
        return {str(row[0]) for row in rows}

    def _to_keyword_query(self, query: str) -> str:
        tokens = re.findall(r'"[^"]+"|\w[\w\-]*', query.lower())
        if not tokens:
            return query
        normalized: list[str] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if token.startswith('"') and token.endswith('"') and len(token) > 2:
                normalized.append(token)
                continue
            if token in {"and", "or", "not", "near"}:
                normalized.append(token.upper())
                continue
            normalized.append(token)
        return " ".join(normalized)

    def _build_lexical_queries(self, query: str) -> tuple[str, str, str | None]:
        if _is_structured_fts_query(query):
            return query, self._to_keyword_query(query), None

        tokens = _extract_query_tokens(query, drop_stopwords=True)
        if not tokens:
            tokens = _extract_query_tokens(query, drop_stopwords=False)
        if not tokens:
            normalized = self._to_keyword_query(query)
            return normalized, normalized, None

        text_query = " AND ".join(tokens)
        keyword_query = " ".join(tokens)
        phrase = _best_query_phrase(query)
        phrase_query = f'"{phrase}"' if phrase else None
        return text_query, keyword_query, phrase_query

    def _get_model(self) -> EmbeddingModel:
        if self._model is None:
            self._model = EmbeddingModel(
                EmbeddingConfig(model_name=self.model_name, batch_size=16, local_files_only=True, quiet=True)
            )
        return self._model

    def _load_embeddings(self) -> None:
        if not self.npz_path or not self.npz_path.exists():
            return
        data = np.load(self.npz_path)
        self._embedding_chunk_ids = data["chunk_ids"].astype(str)
        self._embedding_matrix = data["embeddings"].astype("float32")


def _normalize_bm25(rows: list[tuple[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    # SQLite bm25: lower score is better; map best->1 and worst->0.
    values = [row[1] for row in rows]
    best = min(values)
    worst = max(values)
    if abs(worst - best) < 1e-9:
        return {chunk_id: 1.0 for chunk_id, _ in rows}

    normalized: dict[str, float] = {}
    for chunk_id, value in rows:
        normalized[chunk_id] = (worst - value) / (worst - best)
    return normalized


def _sanitize_fts_query(query: str) -> str:
    tokens = re.findall(r"\w[\w\-]*", query.lower())
    return " ".join(tokens)


_FTS_BOOLEAN_TERMS = {"and", "or", "not", "near"}
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "these",
    "this",
    "to",
    "was",
    "were",
    "with",
}


def _is_structured_fts_query(query: str) -> bool:
    return bool(re.search(r'"|\(|\)|\*|\b(?:and|or|not|near)\b', query, flags=re.IGNORECASE))


def _extract_query_tokens(query: str, drop_stopwords: bool) -> list[str]:
    raw_tokens = re.findall(r"\w[\w\-]*", query.lower())
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _FTS_BOOLEAN_TERMS:
            continue
        if drop_stopwords and token in _QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _best_query_phrase(query: str) -> str | None:
    raw_tokens = re.findall(r"\w[\w\-]*", query.lower())
    runs: list[list[str]] = []
    current: list[str] = []
    for token in raw_tokens:
        if token in _FTS_BOOLEAN_TERMS or token in _QUERY_STOPWORDS:
            if len(current) >= 2:
                runs.append(current)
            current = []
            continue
        current.append(token)
    if len(current) >= 2:
        runs.append(current)
    if not runs:
        return None
    longest = max(runs, key=len)
    return " ".join(longest)
