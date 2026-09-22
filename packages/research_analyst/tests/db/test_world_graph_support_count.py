"""support_count moves only when a new provenance row is inserted."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import EdgeResolution, NodeResolution
from research_analysis_layer.services.graph_updater import GraphUpdater


def _node(**overrides: object) -> NodeResolution:
    payload = {
        "node_key": "concept:rates",
        "node_type": "concept",
        "canonical_label": "Rates",
        "summary_text": "first summary",
        "status": "proposed",
        "authority_band": "seed",
        "support_count": 4,
        "chunk_order": 1,
        "assertion_order": 1,
        "evidence_text": "rates fell",
    }
    payload.update(overrides)
    return NodeResolution(**payload)


def _edge(**overrides: object) -> EdgeResolution:
    payload = {
        "edge_key": "impacts:rates->dollar",
        "from_node_key": "concept:rates",
        "to_node_key": "concept:dollar",
        "edge_type": "impacts",
        "status": "proposed",
        "authority_band": "seed",
        "maturity": "trace",
        "support_count": 4,
        "chunk_order": 1,
        "assertion_order": 1,
        "evidence_text": "rates fell",
    }
    payload.update(overrides)
    return EdgeResolution(**payload)


class WorldGraphSupportCountTest(unittest.TestCase):
    def _rows(self, store: AnalysisStore) -> tuple[dict, dict]:
        with store._connect() as conn:
            nodes = {
                row["node_key"]: dict(row)
                for row in conn.execute(
                    """
                    SELECT node_key, canonical_label, summary_text, status,
                           authority_band, support_count
                    FROM world_nodes
                    """
                ).fetchall()
            }
            edges = {
                row["edge_key"]: dict(row)
                for row in conn.execute(
                    """
                    SELECT edge_key, status, authority_band, maturity, support_count
                    FROM world_edges
                    """
                ).fetchall()
            }
        return nodes, edges

    def test_support_count_is_one_per_new_provenance_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AnalysisStore(Path(tmp) / "analysis.db")
            updater = GraphUpdater(store)

            updater.apply_resolutions(
                [_node()],
                [_edge()],
                run_id=1,
                research_id=7,
                document_hash="hash-7",
            )
            nodes, edges = self._rows(store)
            self.assertEqual(nodes["concept:rates"]["support_count"], 1)
            self.assertEqual(edges["impacts:rates->dollar"]["support_count"], 1)

            updater.apply_resolutions(
                [
                    _node(
                        canonical_label="Policy rates",
                        summary_text="revised summary",
                        status="reinforced",
                        authority_band="emerging",
                    )
                ],
                [
                    _edge(
                        status="supported",
                        authority_band="established",
                        maturity="path",
                    )
                ],
                run_id=2,
                research_id=7,
                document_hash="hash-7",
            )
            nodes, edges = self._rows(store)
            self.assertEqual(nodes["concept:rates"]["support_count"], 1)
            self.assertEqual(nodes["concept:rates"]["canonical_label"], "Policy rates")
            self.assertEqual(nodes["concept:rates"]["summary_text"], "revised summary")
            self.assertEqual(nodes["concept:rates"]["status"], "reinforced")
            self.assertEqual(nodes["concept:rates"]["authority_band"], "emerging")
            self.assertEqual(edges["impacts:rates->dollar"]["support_count"], 1)
            self.assertEqual(edges["impacts:rates->dollar"]["status"], "supported")
            self.assertEqual(edges["impacts:rates->dollar"]["authority_band"], "established")
            self.assertEqual(edges["impacts:rates->dollar"]["maturity"], "path")

            updater.apply_resolutions(
                [_node(assertion_order=2, evidence_text="a second print")],
                [_edge(assertion_order=2, evidence_text="a second print")],
                run_id=3,
                research_id=7,
                document_hash="hash-7",
            )
            nodes, edges = self._rows(store)
            self.assertEqual(nodes["concept:rates"]["support_count"], 2)
            self.assertEqual(edges["impacts:rates->dollar"]["support_count"], 2)


if __name__ == "__main__":
    unittest.main()
