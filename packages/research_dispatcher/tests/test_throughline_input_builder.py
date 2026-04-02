import unittest

from src.report_models import DispatchBatch
from src.throughline_input_builder import ThroughlineInputBuilder


class ThroughlineInputBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = ThroughlineInputBuilder()

    def test_build_from_legacy_documents_preserves_existing_shape(self):
        documents = [
            {
                "id": 1,
                "document_name": "Rates Daily",
                "source": "Goldman Sachs",
                "source_date": "2026-03-30",
                "parsed_data": {
                    "themes": [
                        {
                            "label": "Higher term premium",
                            "context": "Term premium remains under upward pressure.",
                            "strength": "Primary",
                            "confidence": "High",
                            "classification": "forecast",
                            "excerpts": ["Term premium is repricing."],
                        }
                    ],
                    "trades": [
                        {
                            "exposure": "Pay 5y rates",
                            "conviction": "High",
                            "timeframe": "weeks",
                            "rationale": "Sticky inflation risk",
                        }
                    ],
                },
            }
        ]

        payload = self.builder.build_from_legacy_documents(documents)

        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["themes"][0]["label"], "Higher term premium")
        self.assertEqual(payload["trades"][0]["text"], "Pay 5y rates")
        self.assertEqual(payload["sources"], ["Goldman Sachs"])

    def test_build_from_batch_exports_richer_signal_sets(self):
        batch = DispatchBatch.from_dict(
            {
                "batch_key": "2026-04-01:us:rates",
                "analysis_version": "2026-04-01",
                "scope": {"region": "US"},
                "cross_document_signals": {
                    "repeated_assertions": [{"key": "term_premium_up"}]
                },
                "documents": [
                    {
                        "research_id": 11,
                        "document_name": "Macro Weekly",
                        "source": "Barclays",
                        "source_date": "2026-03-31",
                        "quality": {"score": 91, "passed": True},
                        "themes": [
                            {
                                "label": "Higher term premium",
                                "context": "Fiscal concerns keep long-end yields elevated.",
                                "strength": "Primary",
                                "confidence": "High",
                                "classification": "forecast",
                                "excerpts": ["Long-end term premium remains biased higher."],
                            }
                        ],
                        "trades": [
                            {
                                "text": "Hold 5s30s steepeners",
                                "conviction": "High",
                                "timeframe": "weeks",
                            }
                        ],
                        "assertions": [
                            {
                                "summary_text": "Payrolls should miss consensus.",
                                "assertion_type": "forecast",
                                "status": "proposed",
                                "authority_band": "seed",
                                "time_horizon": "days",
                            }
                        ],
                        "world_nodes": [
                            {
                                "node_key": "n_term_premium",
                                "node_type": "concept",
                                "canonical_label": "Term premium",
                                "support_count": 4,
                            }
                        ],
                        "world_edges": [
                            {
                                "edge_key": "e_supply_term_premium",
                                "from_node_key": "n_supply",
                                "to_node_key": "n_term_premium",
                                "edge_type": "drives",
                                "support_count": 2,
                            }
                        ],
                        "forecast_candidates": [
                            {
                                "indicator_key": "us_nfp",
                                "event_name": "Nonfarm Payrolls",
                                "release_date": "2026-04-03",
                                "forecast_value_text": "145k",
                                "match_status": "matched",
                                "review_status": "approved",
                            }
                        ],
                    }
                ],
            }
        )

        payload = self.builder.build_from_batch(batch)

        self.assertEqual(payload["batch_key"], "2026-04-01:us:rates")
        self.assertEqual(payload["analysis_version"], "2026-04-01")
        self.assertEqual(payload["themes"][0]["quality_score"], 91.0)
        self.assertEqual(payload["assertions"][0]["summary_text"], "Payrolls should miss consensus.")
        self.assertEqual(payload["world_nodes"][0]["canonical_label"], "Term premium")
        self.assertEqual(payload["forecasts"][0]["event_name"], "Nonfarm Payrolls")
        self.assertEqual(
            payload["cross_document_signals"]["repeated_assertions"][0]["key"],
            "term_premium_up",
        )

    def test_dispatch_batch_can_round_trip_to_legacy_records(self):
        batch = DispatchBatch.from_dict(
            {
                "batch_key": "2026-04-01:legacy-roundtrip",
                "documents": [
                    {
                        "research_id": 12,
                        "document_hash": "hash-12",
                        "file_id": "drive-12",
                        "document_name": "Desk Note",
                        "source": "MS",
                        "source_date": "2026-03-29",
                        "publisher": "Morgan Stanley",
                        "region": "US",
                        "asset_focus": "rates",
                        "document_link": "https://example.test/doc/12",
                        "themes": [{"label": "Carry remains attractive"}],
                        "trades": [{"text": "Own front-end carry"}],
                    }
                ],
            }
        )

        legacy = batch.to_legacy_records()

        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]["id"], 12)
        self.assertEqual(legacy[0]["parsed_data"]["metadata"]["publisher"], "Morgan Stanley")
        self.assertEqual(legacy[0]["parsed_data"]["themes"][0]["label"], "Carry remains attractive")


if __name__ == "__main__":
    unittest.main()
