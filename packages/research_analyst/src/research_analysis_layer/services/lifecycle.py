"""World-model lifecycle updates for the deterministic bootstrap."""

from __future__ import annotations

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import EdgeResolution, NodeResolution


class LifecycleService:
    """Apply lightweight lifecycle updates after graph writes."""

    def __init__(self, store: AnalysisStore):
        self.store = store

    def update_node_state(self, nodes: list[NodeResolution]) -> int:
        node_keys = [node.node_key for node in nodes]
        return self.store.refresh_world_node_lifecycle(node_keys)

    def update_edge_state(self, edges: list[EdgeResolution]) -> int:
        edge_keys = [edge.edge_key for edge in edges]
        return self.store.refresh_world_edge_lifecycle(edge_keys)

    def evaluate_temporal_updates(
        self,
        nodes: list[NodeResolution],
        edges: list[EdgeResolution],
    ) -> dict[str, int]:
        return {
            "nodes_updated": self.update_node_state(nodes),
            "edges_updated": self.update_edge_state(edges),
        }
