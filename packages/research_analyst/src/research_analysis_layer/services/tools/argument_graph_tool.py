"""Analyst-local argument-graph tool (Slice 2 Task 5 leftover).

Additive to corpus `research_search`. Schema is registered on ToolRegistry
in-process so `schemas/corpus_tool_schema.json` stays corpus-only.
Positions in every hit are publishers.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from research_analysis_layer.models.argument_graph_models import ArgumentGraphSnapshot
from research_analysis_layer.services.argument_graph import ArgumentGraph

ARGUMENT_GRAPH_TOOL_NAME = "argument_graph"
_MAX_HITS = 8
_MAX_TEXT_CHARS = 400

QUERY_ALIASES = {
    "same_evidence": "interpretation_gaps",
    "interpretation_gaps": "interpretation_gaps",
    "independence": "independence",
    "herding": "independence",
    "contradicts": "contradictions",
    "contradictions": "contradictions",
    "backed": "backed_vs_asserted",
    "backed_vs_asserted": "backed_vs_asserted",
    "all": "all",
}

ARGUMENT_GRAPH_TOOL_SCHEMA: dict[str, Any] = {
    "name": ARGUMENT_GRAPH_TOOL_NAME,
    "description": (
        "Query resolved argument maps across publishers: same-evidence "
        "interpretation gaps, robust vs herding consensus, evidence that "
        "contradicts a claim, and backed-vs-asserted splits. A position is "
        "always a publisher, never a thesis/contrarian/positioning lens. "
        "Use this to ask who disagrees (or agrees) on a claim and on what "
        "evidence. Do not use it to retrieve corpus passages — that is "
        "`research_search`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Which join to run. One of interpretation_gaps "
                    "(same evidence, opposing conclusions), independence "
                    "(robust vs herding), contradictions, "
                    "backed_vs_asserted, or all. Default all."
                ),
            },
            "claim_key": {
                "type": "string",
                "description": (
                    "Optional resolved claim key to scope the join, e.g. "
                    "claim:fed_policy:hike:down. Omit to query the stored window."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max hits per query type. Default 8.",
                "default": 8,
                "minimum": 1,
                "maximum": 8,
            },
        },
    },
}


def create_argument_graph_handlers(
    store: Any | None = None,
    *,
    min_publishers: int = 2,
    maps: Sequence[Mapping[str, Any]] | None = None,
    graph: ArgumentGraph | None = None,
) -> dict[str, Any]:
    """Create ToolRegistry handlers for argument-graph queries."""
    tool = ArgumentGraphTool(
        store=store,
        min_publishers=min_publishers,
        maps=maps,
        graph=graph,
    )
    return {ARGUMENT_GRAPH_TOOL_NAME: tool.handle}


class ArgumentGraphTool:
    """Run ArgumentGraph queries over stored (or injected) maps."""

    def __init__(
        self,
        *,
        store: Any | None = None,
        min_publishers: int = 2,
        maps: Sequence[Mapping[str, Any]] | None = None,
        graph: ArgumentGraph | None = None,
    ) -> None:
        self._store = store
        self._maps = None if maps is None else tuple(maps)
        self._graph = graph or ArgumentGraph(min_publishers=min_publishers)

    def handle(self, input_data: dict[str, Any]) -> dict[str, Any]:
        raw_query = input_data.get("query") or "all"
        if not isinstance(raw_query, str):
            raise ValueError("query must be a string")
        wanted = raw_query.strip().lower().replace("-", "_")
        field = QUERY_ALIASES.get(wanted)
        if field is None:
            allowed = ", ".join(sorted(set(QUERY_ALIASES.values())))
            raise ValueError(f"unknown query: {raw_query!r}; allowed: {allowed}")

        claim_key = input_data.get("claim_key")
        if claim_key is not None and not isinstance(claim_key, str):
            raise ValueError("claim_key must be a string")
        if isinstance(claim_key, str) and not claim_key.strip():
            claim_key = None

        limit = input_data.get("limit", _MAX_HITS)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, _MAX_HITS))

        snapshot = self._graph.query_maps(self._load_maps(), claim_key=claim_key)
        return _payload(snapshot, field=field, claim_key=claim_key, limit=limit)

    def _load_maps(self) -> Sequence[Mapping[str, Any]]:
        if self._maps is not None:
            return self._maps
        if self._store is None:
            raise ValueError("argument_graph tool has no analysis store")
        return self._store.list_argument_maps_for_consensus()


def _payload(
    snapshot: ArgumentGraphSnapshot,
    *,
    field: str,
    claim_key: str | None,
    limit: int,
) -> dict[str, Any]:
    base = {
        "claim_key": claim_key,
        "min_publishers": snapshot.min_publishers,
        "clustered_claim_count": snapshot.clustered_claim_count,
        "skipped_unresolved_count": snapshot.skipped_unresolved_count,
    }
    buckets = {
        "interpretation_gaps": [
            _gap_payload(item) for item in snapshot.interpretation_gaps
        ],
        "independence": [
            _independence_payload(item) for item in snapshot.independence
        ],
        "contradictions": [
            _contradiction_payload(item) for item in snapshot.contradictions
        ],
        "backed_vs_asserted": [
            _backed_payload(item) for item in snapshot.backed_vs_asserted
        ],
    }
    if field == "all":
        result = dict(base)
        result["query"] = "all"
        for name, rows in buckets.items():
            result[name] = _bounded(rows, limit)
        return result

    rows = buckets[field]
    return {
        **base,
        "query": field,
        **_bounded(rows, limit),
    }


def _bounded(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        "hits": rows[:limit],
        "hit_count": len(rows),
        "truncated": len(rows) > limit,
    }


def _gap_payload(item: Any) -> dict[str, Any]:
    return {
        "referent_key": item.referent_key,
        "family": item.family,
        "source_diversity": item.source_diversity,
        "sides": [_side_payload(side) for side in item.sides],
        "rationale": _truncate(item.rationale),
    }


def _independence_payload(item: Any) -> dict[str, Any]:
    return {
        "claim_key": item.claim_key,
        "kind": item.kind,
        "source_diversity": item.source_diversity,
        "positions": list(item.positions),
        "shared_referents": list(item.shared_referents)[:_MAX_HITS],
        "rationale": _truncate(item.rationale),
    }


def _contradiction_payload(item: Any) -> dict[str, Any]:
    return {
        "claim_key": item.claim_key,
        "publisher": item.publisher,
        "research_id": item.research_id,
        "claim": _truncate(item.claim),
        "polarity": item.polarity,
        "referent_key": item.referent_key,
        "opposing_sides": [_side_payload(side) for side in item.opposing_sides],
        "rationale": _truncate(item.rationale),
    }


def _backed_payload(item: Any) -> dict[str, Any]:
    return {
        "claim_key": item.claim_key,
        "source_diversity": item.source_diversity,
        "evidenced": list(item.evidenced),
        "asserted": list(item.asserted),
        "reasoned": list(item.reasoned),
        "rationale": _truncate(item.rationale),
    }


def _side_payload(side: Any) -> dict[str, Any]:
    return {
        "publisher": side.publisher,
        "research_id": side.research_id,
        "claim": _truncate(side.claim),
        "claim_key": side.claim_key,
        "polarity": side.polarity,
        "rationale": _truncate(side.rationale),
        "support_strength": side.support_strength,
        "evidence_text": _truncate(side.evidence_text),
        "referent_keys": list(side.referent_keys)[:_MAX_HITS],
    }


def _truncate(value: Any, *, limit: int = _MAX_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text
