"""Graph persistence wrapper."""

from __future__ import annotations

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import EdgeResolution, GraphUpdateResult, NodeResolution


class GraphUpdater:
    """Persist resolved nodes and edges."""

    def __init__(self, store: AnalysisStore):
        self.store = store

    def apply_resolutions(
        self,
        nodes: list[NodeResolution],
        edges: list[EdgeResolution],
        *,
        run_id: int,
        research_id: int,
        document_hash: str,
    ) -> GraphUpdateResult:
        node_count = self.store.upsert_world_nodes(nodes)
        edge_count = self.store.upsert_world_edges(edges)
        self.store.record_graph_provenance(
            run_id=run_id,
            research_id=research_id,
            document_hash=document_hash,
            nodes=nodes,
            edges=edges,
        )
        open_question_count = sum(1 for node in nodes if node.node_type == "open_question")
        return GraphUpdateResult(
            node_upsert_count=node_count,
            edge_upsert_count=edge_count,
            open_question_count=open_question_count,
        )
