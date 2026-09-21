# Preserved from packages/research-store/distill_tool/search.py (Phase 1).
# Reference only — not imported. Canonical retrieval port is Phase 2+.
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from distill_tool.embeddings import EmbeddingConfig, EmbeddingModel
from distill_tool.keywords import normalize_term


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    run_id: str
    source_path: str | None
    source_date: str | None
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
        self._table_exists_cache: dict[str, object] = {}
        self._load_embeddings()

    def search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword_weight: float = 0.55,
        semantic_weight: float = 0.45,
        min_lexical_score: float = 0.05,
        semantic_tail_mode: str = "filter",
        semantic_tail_penalty: float = 0.25,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query or limit <= 0:
            return []

        date_allowed = self._chunk_ids_for_date_range(date_from, date_to)

        self._last_semantic_error = None
        lexical_candidate_limit = max(limit * 25, 200)
        semantic_candidate_limit = max(limit * 40, 400)

        lexical_scores: dict[str, float] = {}
        if keyword_weight > 0.0 or semantic_weight <= 0.0:
            lexical_scores = self._lexical_scores(query, run_id=run_id, limit=lexical_candidate_limit)

        semantic_scores: dict[str, float] = {}
        if semantic_weight > 0.0:
            semantic_scores = self._semantic_scores(
                query, run_id=run_id, limit=semantic_candidate_limit,
                allowed_chunk_ids=date_allowed,
            )

        if semantic_weight > 0.0 and not semantic_scores:
            if not lexical_scores:
                lexical_scores = self._lexical_scores(query, run_id=run_id, limit=lexical_candidate_limit)
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

        if date_allowed is not None and lexical_scores:
            lexical_scores = {k: v for k, v in lexical_scores.items() if k in date_allowed}

        all_chunk_ids = set(lexical_scores) | set(semantic_scores)
        if not all_chunk_ids:
            return []

        min_lexical_score = max(0.0, min_lexical_score)
        semantic_tail_penalty = max(0.0, min(1.0, semantic_tail_penalty))
        semantic_tail_mode = semantic_tail_mode.lower().strip()
        if semantic_tail_mode not in {"filter", "demote", "allow"}:
            semantic_tail_mode = "filter"
        lexical_constraints_active = keyword_weight > 0.0 and any(score > 0.0 for score in lexical_scores.values())
        lexical_ranks = _rank_map(lexical_scores)
        semantic_ranks = _rank_map(semantic_scores)

        final_scores: list[tuple[str, float, float, float]] = []
        for chunk_id in all_chunk_ids:
            lexical = lexical_scores.get(chunk_id, 0.0)
            semantic = semantic_scores.get(chunk_id, 0.0)
            hybrid = _reciprocal_rank_fusion(
                lexical_rank=lexical_ranks.get(chunk_id),
                semantic_rank=semantic_ranks.get(chunk_id),
                keyword_weight=keyword_weight,
                semantic_weight=semantic_weight,
            )
            # Preserve score magnitude as a tiebreaker after reciprocal-rank fusion.
            hybrid += 0.05 * ((keyword_weight * lexical) + (semantic_weight * semantic))

            if lexical_constraints_active and semantic > 0.0 and lexical <= 0.0:
                if semantic_tail_mode == "filter":
                    continue
                if semantic_tail_mode == "demote":
                    hybrid *= semantic_tail_penalty

            if lexical_constraints_active and min_lexical_score > 0.0 and 0.0 <= lexical < min_lexical_score:
                hybrid *= lexical / min_lexical_score

            final_scores.append((chunk_id, lexical, semantic, hybrid))

        if not final_scores:
            return []

        metadata = self._load_chunk_metadata([row[0] for row in final_scores])
        hash_counts = self._load_text_hash_counts(
            {
                chunk["text_hash"]
                for chunk in metadata.values()
                if chunk.get("text_hash")
            }
        )

        rescored: list[tuple[str, float, float, float]] = []
        for chunk_id, lexical, semantic, hybrid in final_scores:
            chunk = metadata.get(chunk_id)
            if not chunk:
                continue
            hybrid *= _duplicate_penalty(hash_counts.get(chunk["text_hash"], 1))
            rescored.append((chunk_id, lexical, semantic, hybrid))

        rescored.sort(key=lambda row: row[3], reverse=True)

        results: list[SearchResult] = []
        seen_hashes: set[str] = set()
        for chunk_id, lexical, semantic, hybrid in rescored:
            chunk = metadata.get(chunk_id)
            if not chunk:
                continue
            text_hash = chunk["text_hash"]
            if text_hash in seen_hashes:
                continue
            seen_hashes.add(text_hash)
            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    run_id=chunk["run_id"],
                    source_path=chunk["source_path"],
                    source_date=chunk["source_date"],
                    page_number=chunk["page_number"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    keywords=chunk["keywords"],
                    lexical_score=lexical,
                    semantic_score=semantic,
                    hybrid_score=hybrid,
                )
            )
            if len(results) >= limit:
                break

        return results

    def _lexical_scores(self, query: str, run_id: str | None, limit: int) -> dict[str, float]:
        text_query, phrase_queries = self._build_text_queries(query)
        text_rows = self._fts_query(
            table="chunks_fts",
            query=text_query,
            run_id=run_id,
            limit=limit,
        )
        keyword_scores = self._keyword_scores(query, run_id=run_id)
        if not keyword_scores and self._table_exists("keyword_fts"):
            keyword_rows = self._fts_query(
                table="keyword_fts",
                query=self._to_keyword_query(query),
                run_id=run_id,
                limit=limit,
            )
            keyword_scores = _normalize_bm25(keyword_rows)

        phrase_scores: dict[str, float] = {}
        for phrase_query in phrase_queries:
            phrase_rows = self._fts_query(
                table="chunks_fts",
                query=phrase_query,
                run_id=run_id,
                limit=limit,
            )
            for chunk_id, score in _normalize_bm25(phrase_rows).items():
                phrase_scores[chunk_id] = max(phrase_scores.get(chunk_id, 0.0), score)

        text_scores = _normalize_bm25(text_rows)
        chunk_ids = set(text_scores) | set(keyword_scores) | set(phrase_scores)

        combined: dict[str, float] = {}
        for chunk_id in chunk_ids:
            if phrase_scores:
                score = (
                    0.50 * keyword_scores.get(chunk_id, 0.0)
                    + 0.30 * text_scores.get(chunk_id, 0.0)
                    + 0.20 * phrase_scores.get(chunk_id, 0.0)
                )
            else:
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

    def _semantic_scores(
        self, query: str, run_id: str | None, limit: int,
        allowed_chunk_ids: set[str] | None = None,
    ) -> dict[str, float]:
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
        else:
            mask = np.ones(len(self._embedding_chunk_ids), dtype=bool)

        if allowed_chunk_ids is not None:
            date_mask = np.array(
                [chunk_id in allowed_chunk_ids for chunk_id in self._embedding_chunk_ids], dtype=bool
            )
            mask = mask & date_mask

        if not np.any(mask):
            return {}

        idxs = np.where(mask)[0]
        subset_scores = similarities[idxs]
        top_n = min(limit, subset_scores.shape[0])
        top_local = np.argpartition(subset_scores, -top_n)[-top_n:]
        top_idxs = idxs[top_local]

        top_pairs = sorted(
            ((int(i), float(similarities[i])) for i in top_idxs),
            key=lambda row: row[1],
            reverse=True,
        )
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
        chunk_columns = self._columns_for_table("chunks")
        has_source_date = "source_date" in chunk_columns
        select_source_date = "source_date" if has_source_date else "NULL AS source_date"
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, run_id, source_path, {select_source_date}, page_number, chunk_index, text, keywords_json, text_hash
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
                "source_date": row[3],
                "page_number": int(row[4]),
                "chunk_index": int(row[5]),
                "text": str(row[6]),
                "keywords": json.loads(row[7]),
                "text_hash": str(row[8]),
            }
        return metadata

    def _columns_for_table(self, table: str) -> set[str]:
        cache_key = f"columns:{table}"
        cached = self._table_exists_cache.get(cache_key)
        if isinstance(cached, set):
            return cached
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        columns = {str(row[1]) for row in rows}
        self._table_exists_cache[cache_key] = columns
        return columns

    def _load_text_hash_counts(self, text_hashes: set[str]) -> dict[str, int]:
        if not text_hashes:
            return {}
        placeholders = ",".join("?" for _ in text_hashes)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT text_hash, COUNT(*)
                FROM chunks
                WHERE text_hash IN ({placeholders})
                GROUP BY text_hash
                """,
                list(text_hashes),
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def _chunk_ids_for_run(self, run_id: str) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT chunk_id FROM chunks WHERE run_id = ?", (run_id,)).fetchall()
        return {str(row[0]) for row in rows}

    def _chunk_ids_for_date_range(
        self, date_from: str | None, date_to: str | None
    ) -> set[str] | None:
        """Return chunk IDs within the date range, or None if no filtering needed.

        Chunks with NULL source_date are excluded from date-filtered queries.
        """
        if date_from is None and date_to is None:
            return None
        sql = "SELECT chunk_id FROM chunks WHERE source_date IS NOT NULL"
        params: list[str] = []
        if date_from is not None:
            sql += " AND source_date >= ?"
            params.append(date_from)
        if date_to is not None:
            sql += " AND source_date <= ?"
            params.append(date_to)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row[0]) for row in rows}

    def _keyword_scores(self, query: str, run_id: str | None) -> dict[str, float]:
        if not self._table_exists("chunk_keywords"):
            return {}

        candidates = _query_keyword_candidates(query)
        if not candidates:
            return {}

        placeholders = ",".join("?" for _ in candidates)
        sql = (
            "SELECT ck.chunk_id, ck.term, ck.source, ck.score "
            "FROM chunk_keywords ck "
            "JOIN chunks c ON c.chunk_id = ck.chunk_id "
            f"WHERE ck.term IN ({placeholders})"
        )
        params: list[object] = list(candidates)
        if run_id:
            sql += " AND c.run_id = ?"
            params.append(run_id)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return {}

        raw_scores: dict[str, float] = {}
        for chunk_id, term, source, score in rows:
            source_key = str(source).strip().lower()
            source_weight = 1.8 if source_key in {"dictionary", "dict"} else 1.0
            term_weight = candidates.get(str(term), 1.0)
            raw_scores[str(chunk_id)] = raw_scores.get(str(chunk_id), 0.0) + (
                max(float(score), 1.0) * source_weight * term_weight
            )
        return _normalize_positive_scores(raw_scores)

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

    def _build_text_queries(self, query: str) -> tuple[str, list[str]]:
        if _is_structured_fts_query(query):
            return query, []

        tokens = _extract_query_tokens(query, drop_stopwords=True)
        if not tokens:
            tokens = _extract_query_tokens(query, drop_stopwords=False)
        if not tokens:
            normalized = self._to_keyword_query(query)
            return normalized, []

        text_query = " AND ".join(tokens)
        phrase_queries = [f'"{phrase}"' for phrase in _query_phrase_candidates(query)]
        return text_query, phrase_queries

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

    def _table_exists(self, table_name: str) -> bool:
        cached = self._table_exists_cache.get(table_name)
        if cached is not None:
            return cached
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ? LIMIT 1",
                (table_name,),
            ).fetchone()
        exists = row is not None
        self._table_exists_cache[table_name] = exists
        return exists


def _normalize_bm25(rows: list[tuple[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    values = [row[1] for row in rows]
    best = min(values)
    worst = max(values)
    if abs(worst - best) < 1e-9:
        return {chunk_id: 1.0 for chunk_id, _ in rows}

    return {
        chunk_id: (worst - value) / (worst - best)
        for chunk_id, value in rows
    }


def _normalize_positive_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    best = max(values)
    worst = min(values)
    if abs(best - worst) < 1e-9:
        return {chunk_id: 1.0 for chunk_id in scores}
    return {
        chunk_id: (value - worst) / (best - worst)
        for chunk_id, value in scores.items()
    }


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
    raw_tokens = normalize_term(query).split()
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _FTS_BOOLEAN_TERMS:
            continue
        if drop_stopwords and token in _QUERY_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def _query_phrase_candidates(query: str) -> list[str]:
    raw_tokens = normalize_term(query).split()
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

    phrases = [" ".join(run) for run in runs if len(run) >= 2]
    phrases.sort(key=lambda value: (-len(value.split()), value))

    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        if phrase in seen:
            continue
        seen.add(phrase)
        deduped.append(phrase)
    return deduped[:3]


def _query_keyword_candidates(query: str) -> dict[str, float]:
    raw_tokens = normalize_term(query).split()
    if not raw_tokens:
        return {}

    filtered_tokens = [token for token in raw_tokens if token not in _QUERY_STOPWORDS]
    tokens = filtered_tokens or raw_tokens
    candidates: dict[str, float] = {}

    for token in tokens:
        candidates[token] = max(candidates.get(token, 0.0), 1.0)

    max_ngram = min(4, len(tokens))
    for ngram_size in range(2, max_ngram + 1):
        for idx in range(len(tokens) - ngram_size + 1):
            phrase = " ".join(tokens[idx : idx + ngram_size])
            candidates[phrase] = max(candidates.get(phrase, 0.0), 1.0 + (0.35 * (ngram_size - 1)))

    for phrase in _query_phrase_candidates(query):
        candidates[phrase] = max(
            candidates.get(phrase, 0.0),
            1.25 + (0.25 * (len(phrase.split()) - 1)),
        )

    return candidates


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return {chunk_id: idx for idx, (chunk_id, _) in enumerate(ranked, start=1)}


def _reciprocal_rank_fusion(
    lexical_rank: int | None,
    semantic_rank: int | None,
    keyword_weight: float,
    semantic_weight: float,
    rrf_k: int = 60,
) -> float:
    score = 0.0
    if lexical_rank is not None:
        score += keyword_weight / (rrf_k + lexical_rank)
    if semantic_rank is not None:
        score += semantic_weight / (rrf_k + semantic_rank)
    return score


def _duplicate_penalty(duplicate_count: int) -> float:
    if duplicate_count <= 1:
        return 1.0
    return 1.0 / (1.0 + math.log10(float(duplicate_count)))
