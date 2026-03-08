from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from distill_tool.search import HybridSearchEngine


@dataclass(frozen=True)
class JudgedQuery:
    query_id: str
    query: str
    relevant_chunk_ids: dict[str, float]
    run_id: str | None = None


@dataclass(frozen=True)
class QueryEvaluation:
    query_id: str
    query: str
    retrieved_chunk_ids: list[str]
    relevant_chunk_ids: dict[str, float]
    recall_at_k: float
    mrr_at_k: float
    ndcg_at_k: float


@dataclass(frozen=True)
class EvaluationSummary:
    num_queries: int
    limit: int
    recall_at_k: float
    mrr_at_k: float
    ndcg_at_k: float
    query_results: list[QueryEvaluation]


def load_judged_queries(path: str | Path) -> list[JudgedQuery]:
    path = Path(path)
    queries: list[JudgedQuery] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        query_id = str(payload.get("query_id") or f"q{line_number}")
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError(f"{path}:{line_number} missing query")
        relevant = _parse_relevance(payload.get("relevant") or payload.get("relevant_chunk_ids"))
        if not relevant:
            raise ValueError(f"{path}:{line_number} missing relevant chunk ids")
        run_id = payload.get("run_id")
        queries.append(
            JudgedQuery(
                query_id=query_id,
                query=query,
                relevant_chunk_ids=relevant,
                run_id=str(run_id) if run_id is not None else None,
            )
        )
    return queries


def evaluate_queries(
    engine: HybridSearchEngine,
    queries: list[JudgedQuery],
    *,
    limit: int,
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
    min_lexical_score: float = 0.05,
    semantic_tail_mode: str = "filter",
    semantic_tail_penalty: float = 0.25,
) -> EvaluationSummary:
    evaluations: list[QueryEvaluation] = []
    for judged_query in queries:
        results = engine.search(
            query=judged_query.query,
            limit=limit,
            run_id=judged_query.run_id,
            keyword_weight=keyword_weight,
            semantic_weight=semantic_weight,
            min_lexical_score=min_lexical_score,
            semantic_tail_mode=semantic_tail_mode,
            semantic_tail_penalty=semantic_tail_penalty,
        )
        retrieved_ids = [result.chunk_id for result in results]
        evaluations.append(
            QueryEvaluation(
                query_id=judged_query.query_id,
                query=judged_query.query,
                retrieved_chunk_ids=retrieved_ids,
                relevant_chunk_ids=judged_query.relevant_chunk_ids,
                recall_at_k=recall_at_k(retrieved_ids, judged_query.relevant_chunk_ids),
                mrr_at_k=mrr_at_k(retrieved_ids, judged_query.relevant_chunk_ids),
                ndcg_at_k=ndcg_at_k(retrieved_ids, judged_query.relevant_chunk_ids),
            )
        )

    if not evaluations:
        return EvaluationSummary(
            num_queries=0,
            limit=limit,
            recall_at_k=0.0,
            mrr_at_k=0.0,
            ndcg_at_k=0.0,
            query_results=[],
        )

    return EvaluationSummary(
        num_queries=len(evaluations),
        limit=limit,
        recall_at_k=sum(item.recall_at_k for item in evaluations) / len(evaluations),
        mrr_at_k=sum(item.mrr_at_k for item in evaluations) / len(evaluations),
        ndcg_at_k=sum(item.ndcg_at_k for item in evaluations) / len(evaluations),
        query_results=evaluations,
    )


def recall_at_k(retrieved_chunk_ids: list[str], relevant_chunk_ids: dict[str, float]) -> float:
    if not relevant_chunk_ids:
        return 0.0
    hits = sum(1 for chunk_id in relevant_chunk_ids if chunk_id in retrieved_chunk_ids)
    return hits / len(relevant_chunk_ids)


def mrr_at_k(retrieved_chunk_ids: list[str], relevant_chunk_ids: dict[str, float]) -> float:
    for idx, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in relevant_chunk_ids:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(retrieved_chunk_ids: list[str], relevant_chunk_ids: dict[str, float]) -> float:
    if not relevant_chunk_ids:
        return 0.0

    dcg = 0.0
    for idx, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        gain = relevant_chunk_ids.get(chunk_id, 0.0)
        if gain <= 0:
            continue
        dcg += (2**gain - 1.0) / math.log2(idx + 1.0)

    ideal_gains = sorted(relevant_chunk_ids.values(), reverse=True)
    ideal_dcg = 0.0
    for idx, gain in enumerate(ideal_gains[: len(retrieved_chunk_ids)], start=1):
        if gain <= 0:
            continue
        ideal_dcg += (2**gain - 1.0) / math.log2(idx + 1.0)

    if ideal_dcg <= 0:
        return 0.0
    return dcg / ideal_dcg


def summary_to_dict(summary: EvaluationSummary) -> dict:
    return {
        "num_queries": summary.num_queries,
        "limit": summary.limit,
        "metrics": {
            "recall_at_k": round(summary.recall_at_k, 6),
            "mrr_at_k": round(summary.mrr_at_k, 6),
            "ndcg_at_k": round(summary.ndcg_at_k, 6),
        },
        "queries": [
            {
                "query_id": item.query_id,
                "query": item.query,
                "retrieved_chunk_ids": item.retrieved_chunk_ids,
                "relevant_chunk_ids": item.relevant_chunk_ids,
                "recall_at_k": round(item.recall_at_k, 6),
                "mrr_at_k": round(item.mrr_at_k, 6),
                "ndcg_at_k": round(item.ndcg_at_k, 6),
            }
            for item in summary.query_results
        ],
    }


def _parse_relevance(value: object) -> dict[str, float]:
    if isinstance(value, dict):
        parsed: dict[str, float] = {}
        for chunk_id, grade in value.items():
            try:
                parsed[str(chunk_id)] = float(grade)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid relevance grade for {chunk_id!r}") from exc
        return parsed

    if isinstance(value, list):
        return {str(chunk_id): 1.0 for chunk_id in value}

    return {}
