"""World-model draft and update results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NodeResolution:
    """Candidate world node update."""

    node_key: str
    node_type: str
    canonical_label: str
    summary_text: str | None = None
    status: str = "proposed"
    authority_band: str = "seed"
    support_count: int = 1
    chunk_order: int | None = None
    assertion_order: int | None = None
    evidence_text: str | None = None
    alias_text: str | None = None


@dataclass(slots=True)
class EdgeResolution:
    """Candidate world edge update."""

    edge_key: str
    from_node_key: str
    to_node_key: str
    edge_type: str
    directionality: str = "directed"
    status: str = "proposed"
    authority_band: str = "seed"
    maturity: str = "trace"
    support_count: int = 1
    chunk_order: int | None = None
    assertion_order: int | None = None
    evidence_text: str | None = None


@dataclass(slots=True)
class GraphUpdateResult:
    """Summary of graph updates."""

    node_upsert_count: int
    edge_upsert_count: int
    open_question_count: int = 0
