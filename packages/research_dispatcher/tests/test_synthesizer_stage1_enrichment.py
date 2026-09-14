import unittest

from src.llm import ModelConfig
from src.synthesizer import (
    MAX_CLUSTER_CONTEXT_CHARS,
    MAX_CLUSTER_ENTRIES,
    MAX_CLUSTER_EXCERPT_CHARS,
    MAX_CLUSTER_EXCERPTS,
    MAX_CROSS_DOCUMENT_CLUSTERS,
    Synthesizer,
)


class SynthesizerStage1EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(
            anthropic_api_key=None,
            openai_api_key=None,
            deepinfra_api_key=None,
            use_skill_pipeline=True,
        )

    def test_enrichment_clusters_term_premium_variants_and_caps_entries(self):
        long_context = "Term premium pressure is building across the curve. " * 12
        long_excerpt = "A long supporting quote about term premium repricing. " * 8
        input_data = {
            "themes": [
                {
                    "label": "term premia",
                    "source": "Goldman Sachs",
                    "document": "A" * 120,
                    "context": long_context,
                    "strength": "Primary",
                    "confidence": "High",
                    "excerpts": [long_excerpt, long_excerpt, long_excerpt],
                    "directionality": {"bullish": 3, "bearish": 1, "misc": "ignore"},
                },
                {
                    "label": "higher term premium",
                    "source": "JPMorgan",
                    "document": "Desk note",
                    "context": long_context,
                    "strength": "Secondary",
                    "confidence": "Medium",
                    "excerpts": [long_excerpt],
                },
                {
                    "label": "term premium",
                    "source": "Barclays",
                    "document": "Macro weekly",
                    "context": long_context,
                    "strength": "Primary",
                    "confidence": "High",
                    "excerpts": [long_excerpt],
                },
                {
                    "label": "rising term premia",
                    "source": "Morgan Stanley",
                    "document": "Another note",
                    "context": long_context,
                    "strength": "Tertiary",
                    "confidence": "Low",
                    "excerpts": [long_excerpt],
                },
            ]
        }

        enriched = self.synthesizer._enrich_with_cross_document_evidence(input_data)
        clusters = enriched["cross_document_clusters"]
        term_premium_cluster = next(
            cluster for cluster in clusters if cluster["canonical_label"] == "term premium"
        )

        self.assertEqual(term_premium_cluster["source_count"], 4)
        self.assertIn("term premia", term_premium_cluster["theme_labels"])
        self.assertIn("term premium", term_premium_cluster["theme_labels"])
        self.assertLessEqual(len(term_premium_cluster["entries"]), MAX_CLUSTER_ENTRIES)

        first_entry = term_premium_cluster["entries"][0]
        self.assertLessEqual(len(first_entry["context"]), MAX_CLUSTER_CONTEXT_CHARS)
        self.assertLessEqual(len(first_entry.get("excerpts", [])), MAX_CLUSTER_EXCERPTS)
        self.assertLessEqual(len(first_entry["excerpts"][0]), MAX_CLUSTER_EXCERPT_CHARS)
        self.assertEqual(first_entry["directionality"], {"bullish": 3, "bearish": 1})

    def test_enrichment_caps_cluster_count(self):
        themes = []
        for index in range(MAX_CROSS_DOCUMENT_CLUSTERS + 3):
            for source in ("Source A", "Source B"):
                themes.append(
                    {
                        "label": f"theme {index}",
                        "source": source,
                        "document": f"Doc {source}",
                        "context": "Signal context",
                        "strength": "Primary",
                        "confidence": "High",
                    }
                )

        enriched = self.synthesizer._enrich_with_cross_document_evidence({"themes": themes})

        self.assertEqual(len(enriched["cross_document_clusters"]), MAX_CROSS_DOCUMENT_CLUSTERS)

    def test_compact_stage1_payload_preserves_cluster_summary(self):
        payload = {
            "themes": [],
            "trades": [],
            "cross_document_clusters": [{"label": "term premium"}],
            "document_count": 2,
            "sources": ["Goldman Sachs", "JPMorgan"],
            "date_range": "2026-03-01 to 2026-03-02",
        }
        config = ModelConfig(provider="deepinfra", model="MiniMaxAI/MiniMax-M2.5")

        compacted = self.synthesizer._prepare_stage1_payload(payload, config)

        self.assertEqual(compacted["cross_document_clusters"], [{"label": "term premium"}])

    def test_stage1_uses_llm_json_adapter(self):
        class FakeClient:
            def generate_json(self, **kwargs):
                return {
                    "title": "Adapter Test",
                    "through_lines": [
                        {
                            "lead": "Term premium repricing drives long-end risk",
                            "supporting_sources": ["Goldman Sachs", "JPMorgan"],
                            "consensus_level": "moderate_consensus",
                            "consensus_anchor": "Markets are pricing higher long-end risk premia",
                            "supporting_themes": ["term premium"],
                            "supporting_trades": ["Pay 10y swaps"],
                            "key_insight": "Goldman Sachs and JPMorgan point to higher term premium.",
                        }
                    ],
                }

        self.synthesizer.client = FakeClient()

        result = self.synthesizer._stage1_throughlines(
            {
                "themes": [
                    {
                        "label": "term premium",
                        "source": "Goldman Sachs",
                        "context": "Long-end risk premia are rising.",
                        "strength": "Primary",
                        "confidence": "High",
                    }
                ],
                "trades": [],
            }
        )

        self.assertEqual(result["title"], "Adapter Test")
        self.assertEqual(len(result["through_lines"]), 1)

    def test_enrichment_builds_assertion_and_forecast_clusters_from_analyst_signals(self):
        input_data = {
            "themes": [
                {
                    "label": "higher term premium",
                    "source": "Goldman Sachs",
                    "document": "Rates Daily",
                    "context": "Long-end risk premia are rising.",
                    "strength": "Primary",
                    "confidence": "High",
                },
                {
                    "label": "term premia",
                    "source": "JPMorgan",
                    "document": "Macro Weekly",
                    "context": "Fiscal concerns lift term premium.",
                    "strength": "Primary",
                    "confidence": "High",
                },
            ],
            "assertions": [
                {
                    "source": "Goldman Sachs",
                    "document": "Rates Daily",
                    "summary_text": "Payrolls should miss consensus.",
                    "assertion_type": "forecast",
                    "status": "supported",
                    "authority_band": "emerging",
                    "time_horizon": "days",
                    "quality_score": 92,
                },
                {
                    "source": "JPMorgan",
                    "document": "Macro Weekly",
                    "summary_text": "Nonfarm payrolls should undershoot consensus.",
                    "assertion_type": "forecast",
                    "status": "supported",
                    "authority_band": "emerging",
                    "time_horizon": "days",
                    "quality_score": 88,
                },
            ],
            "forecasts": [
                {
                    "source": "Goldman Sachs",
                    "document": "Rates Daily",
                    "indicator_key": "us_nfp",
                    "event_name": "Nonfarm Payrolls",
                    "release_date": "2026-04-03",
                    "forecast_value_text": "145k",
                    "match_status": "matched",
                    "review_status": "approved",
                    "extraction_confidence": "high",
                },
                {
                    "source": "JPMorgan",
                    "document": "Macro Weekly",
                    "indicator_key": "us_nfp",
                    "event_name": "Nonfarm Payrolls",
                    "release_date": "2026-04-03",
                    "forecast_value_text": "150k",
                    "match_status": "matched",
                    "review_status": "approved",
                    "extraction_confidence": "high",
                },
            ],
        }

        enriched = self.synthesizer._enrich_with_cross_document_evidence(input_data)
        clusters = enriched["cross_document_clusters"]

        assertion_cluster = next(
            cluster
            for cluster in clusters
            if cluster["cluster_type"] == "assertion"
            and "payrolls" in cluster["canonical_label"]
        )
        forecast_cluster = next(
            cluster
            for cluster in clusters
            if cluster["cluster_type"] == "forecast"
            and cluster["canonical_label"] == "us_nfp"
        )

        self.assertEqual(assertion_cluster["source_count"], 2)
        self.assertEqual(assertion_cluster["assertion_type"], "forecast")
        self.assertEqual(forecast_cluster["forecast_count"], 2)
        self.assertEqual(forecast_cluster["entries"][0]["event_name"], "Nonfarm Payrolls")

    def test_enrichment_builds_edge_clusters_when_node_labels_are_available(self):
        input_data = {
            "themes": [],
            "world_edges": [
                {
                    "source": "Goldman Sachs",
                    "document": "Rates Daily",
                    "from_label": "Treasury supply",
                    "to_label": "Term premium",
                    "edge_type": "drives",
                    "status": "supported",
                    "authority_band": "emerging",
                    "support_count": 2,
                },
                {
                    "source": "JPMorgan",
                    "document": "Macro Weekly",
                    "from_label": "Treasury supply",
                    "to_label": "Term premium",
                    "edge_type": "drives",
                    "status": "supported",
                    "authority_band": "emerging",
                    "support_count": 3,
                },
            ],
        }

        enriched = self.synthesizer._enrich_with_cross_document_evidence(input_data)
        edge_cluster = next(
            cluster
            for cluster in enriched["cross_document_clusters"]
            if cluster["cluster_type"] == "edge"
        )

        self.assertEqual(edge_cluster["source_count"], 2)
        self.assertIn("Treasury supply drives Term premium", edge_cluster["label"])


if __name__ == "__main__":
    unittest.main()
