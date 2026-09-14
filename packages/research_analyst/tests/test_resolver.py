from __future__ import annotations

import unittest

from research_analysis_layer.models import AssertionDraft
from research_analysis_layer.services.resolver import Resolver


class ResolverTest(unittest.TestCase):
    def test_resolves_concept_node(self) -> None:
        assertion = AssertionDraft(
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
            text="Delayed cuts: Cuts are less likely in June.",
            normalized_text="delayed cuts cuts are less likely in june",
            summary_text="Delayed cuts",
        )
        nodes = Resolver().resolve_nodes([assertion])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].node_type, "forecast")
        self.assertTrue(nodes[0].node_key.startswith("forecast:"))

    def test_builds_edge_for_causal_claim(self) -> None:
        assertion = AssertionDraft(
            chunk_order=1,
            assertion_order=1,
            assertion_type="causal_claim",
            text="Sticky inflation drives higher terminal rates.",
            normalized_text="sticky inflation drives higher terminal rates",
            summary_text="Sticky inflation",
            subject_text="Sticky inflation",
            object_text="higher terminal rates",
        )

        resolver = Resolver()
        nodes = resolver.resolve_nodes([assertion])
        edges = resolver.resolve_edges([assertion], nodes)

        self.assertEqual(len(nodes), 2)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].edge_type, "drives")
        self.assertIn("concept:sticky inflation", edges[0].edge_key)


if __name__ == "__main__":
    unittest.main()
