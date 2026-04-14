import json
import tempfile
import unittest
from pathlib import Path

from src.analyst_client import AnalystBatchClient


class AnalystBatchClientTests(unittest.TestCase):
    def test_load_batch_parses_documents_and_cross_document_signals(self):
        payload = {
            "batch_key": "2026-04-01:us:rates",
            "analysis_version": "2026-04-01",
            "generated_at": "2026-04-01T08:55:00Z",
            "scope": {"region": "US", "asset_focus": "rates"},
            "documents": [
                {
                    "research_id": 101,
                    "document_hash": "abc123",
                    "file_id": "drive-1",
                    "document_name": "Rates Weekly",
                    "source": "JPMorgan",
                    "source_date": "2026-03-31",
                    "publisher": "JPMorgan",
                    "region": "US",
                    "asset_focus": "rates",
                    "document_link": "https://example.test/doc/1",
                    "quality": {"score": 88, "passed": True, "warnings": ["minor_gap"]},
                    "themes": [
                        {
                            "label": "Higher term premium",
                            "context": "Supply and fiscal risk keep term premium elevated.",
                            "strength": "Primary",
                            "confidence": "High",
                            "classification": "forecast",
                            "excerpts": ["Term premium is rising."],
                        }
                    ],
                    "trades": [
                        {
                            "text": "Receive front-end gamma",
                            "conviction": "High",
                            "timeframe": "weeks",
                        }
                    ],
                    "assertions": [
                        {
                            "summary_text": "Payrolls should undershoot consensus.",
                            "assertion_type": "forecast",
                            "status": "proposed",
                            "authority_band": "seed",
                        }
                    ],
                    "world_nodes": [
                        {"node_key": "n1", "canonical_label": "Term premium", "support_count": 3}
                    ],
                    "world_edges": [
                        {"edge_key": "e1", "edge_type": "drives", "support_count": 2}
                    ],
                    "forecast_candidates": [
                        {
                            "indicator_key": "us_nfp",
                            "event_name": "Nonfarm Payrolls",
                            "forecast_value_text": "145k",
                            "review_status": "approved",
                        }
                    ],
                    "trading_opportunities": [
                        {
                            "thesis": "Bear steepener via supply pressure",
                            "direction": "short",
                            "instrument": "10Y Treasury",
                            "timeframe": "weeks",
                            "conviction": "high",
                            "rationale": "Supply and fiscal risk lift long-end yields.",
                            "supporting_excerpts": ["Term premium is rising."],
                            "risks": ["Soft payrolls could flatten the curve."],
                        }
                    ],
                    "short_time_horizon_insights": [
                        {
                            "theme": "Payroll downside risk",
                            "insight": "A soft NFP print would validate front-end receivers.",
                            "timeframe_ref": "days",
                            "confidence": "medium",
                            "supporting_excerpt": "Payrolls should undershoot consensus.",
                            "relevance": ["macro", "rates"],
                        }
                    ],
                    "talking_points": [
                        {
                            "text": "Rates desks are being paid to fade soft-landing confidence.",
                            "context": "Supply and payroll risk both point at higher volatility.",
                            "source_theme": "Higher term premium",
                            "presentation_use": "headline",
                            "target_audience": "internal",
                        }
                    ],
                }
            ],
            "cross_document_signals": {"repeated_assertions": [{"key": "payrolls_miss"}]},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dispatch_batch.json"
            path.write_text(json.dumps(payload))
            batch = AnalystBatchClient(path).load_batch()

        self.assertEqual(batch.batch_key, "2026-04-01:us:rates")
        self.assertEqual(len(batch.documents), 1)
        self.assertEqual(batch.documents[0].research_id, 101)
        self.assertEqual(batch.documents[0].themes[0].label, "Higher term premium")
        self.assertEqual(
            batch.documents[0].trading_opportunities[0].instrument,
            "10Y Treasury",
        )
        self.assertEqual(
            batch.documents[0].short_time_horizon_insights[0].timeframe_ref,
            "days",
        )
        self.assertEqual(
            batch.documents[0].talking_points[0].presentation_use,
            "headline",
        )
        self.assertEqual(
            batch.cross_document_signals["repeated_assertions"][0]["key"],
            "payrolls_miss",
        )

    def test_load_batch_rejects_missing_batch_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dispatch_batch.json"
            path.write_text(json.dumps({"documents": []}))
            with self.assertRaises(ValueError):
                AnalystBatchClient(path).load_batch()


if __name__ == "__main__":
    unittest.main()
