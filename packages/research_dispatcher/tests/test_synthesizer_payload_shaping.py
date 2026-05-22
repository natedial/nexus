import unittest

from src.llm import ModelConfig
from src.synthesizer import Synthesizer


class PayloadShapingTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)
        self.config = ModelConfig(provider="openai", model="gpt-5-mini")

    def test_stage1_payload_only_contains_declared_keys(self):
        enriched = {
            "themes": [{"label": "oil", "context": "x"}],
            "trades": [{"text": "buy", "conviction": "high"}],
            "cross_document_clusters": [],
            "document_count": 4,
            "sources": ["GS"],
            "date_range": "2026-05-01 to 2026-05-07",
            # keys the synthesizer prompt never references:
            "talking_points": [{"text": "noise"}],
            "world_nodes": [{"node_key": "n1"}],
            "trading_opportunities": [{"thesis": "noise"}],
        }
        payload = self.synthesizer._prepare_stage1_payload(enriched, self.config)
        for stray_key in ("talking_points", "world_nodes", "trading_opportunities"):
            self.assertNotIn(stray_key, payload)
        self.assertIn("themes", payload)
        self.assertIn("trades", payload)
        self.assertIn("cross_document_clusters", payload)


class AnalysisPayloadShapeTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)

    def test_theme_clusters_do_not_duplicate_through_line_metadata(self):
        through_lines = [
            {
                "lead": "Oil shock caps hikes",
                "consensus_level": "moderate_consensus",
                "consensus_anchor": "The Fed looks through supply shocks.",
                "supporting_sources": ["GS"],
                "supporting_themes": ["oil shock"],
                "key_insight": "Detailed insight text.",
            }
        ]
        input_data = {
            "themes": [
                {"label": "oil shock", "source": "GS", "document": "GS Weekly",
                 "context": "ctx", "strength": "Primary", "confidence": "High"}
            ],
        }
        payload = self.synthesizer._build_analysis_payload(
            title="T", through_lines=through_lines, input_data=input_data, scope={},
        )
        cluster = payload["theme_clusters"][0]
        # The cluster keeps only its id + theme evidence; through-line metadata
        # lives once, in payload["through_lines"].
        self.assertEqual(set(cluster.keys()), {"id", "themes"})
        self.assertEqual(payload["through_lines"][0]["lead"], "Oil shock caps hikes")


class Stage1ScopeTests(unittest.TestCase):
    def setUp(self):
        self.synthesizer = Synthesizer(use_skill_pipeline=True)

    def test_stage1_payload_carries_scope_context(self):
        captured = {}

        def fake_generate_json(**kwargs):
            captured["user"] = kwargs["user"]
            return {"title": "T", "through_lines": [{"lead": "x"}]}

        self.synthesizer.client.generate_json = fake_generate_json
        self.synthesizer._stage1_throughlines(
            {"themes": [{"label": "fx"}], "trades": [],
             "scope": {"asset_focus": "FX"}},
        )
        self.assertIn("FX", captured["user"])


if __name__ == "__main__":
    unittest.main()
