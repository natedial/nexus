"""Tests for R6: Validate dispatcher ingestion against realistic analyst output."""

import json
import tempfile
import unittest
from pathlib import Path

from src.report_models import DispatchBatch


class TestR6DispatcherIngestion(unittest.TestCase):
    """R6: Validate dispatcher ingestion against realistic analyst output."""

    def test_analyst_batch_shape_accepted_by_dispatch_batch_from_dict(self):
        """DispatchBatch.from_dict() accepts analyst batch shape."""
        analyst_batch = {
            "batch_key": "test-batch",
            "analysis_version": "v1",
            "generated_at": "2026-04-13T10:00:00Z",
            "scope": {"date_from": "2026-04-01"},
            "documents": [
                {
                    "document_key": "doc-001",
                    "document_name": "doc-001",
                    "research_id": 12345,
                    "document_hash": "hashabc123",
                    "source": "JPMorgan",
                    "source_date": "2026-04-10",
                    "publisher": "JPMorgan",
                    "region": "US",
                    "asset_focus": "rates",
                    "document_link": "https://example.com/doc/1",
                    "quality": {"score": 85, "passed": True},
                    "themes": [
                        {
                            "label": "Higher term premium",
                            "context": "Term premium is rising",
                            "strength": "Primary",
                            "confidence": "High",
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
                            "summary_text": "Test assertion",
                            "assertion_type": "forecast",
                            "status": "proposed",
                        }
                    ],
                    "world_nodes": [{"node_key": "n1", "canonical_label": "Test"}],
                    "world_edges": [{"edge_key": "e1", "edge_type": "drives"}],
                    "forecast_candidates": [
                        {"indicator_key": "us_nfp", "event_name": "NFP"}
                    ],
                    "thesis": "Test thesis",
                    "contrarian_view": "Contrarian view",
                    "recommended_positioning": "Position",
                    "cross_document_references": [
                        {
                            "chunk_id": "chunk-1",
                            "source_path": "/tmp/doc-a.pdf",
                            "source_date": "2026-04-09",
                            "text": "Supporting passage",
                            "relevance_score": 0.82,
                        }
                    ],
                }
            ],
            "cross_document_signals": {},
        }

        batch = DispatchBatch.from_dict(analyst_batch)

        self.assertEqual(batch.batch_key, "test-batch")
        self.assertEqual(len(batch.documents), 1)
        doc = batch.documents[0]
        self.assertEqual(doc.research_id, 12345)
        self.assertEqual(doc.document_hash, "hashabc123")
        self.assertEqual(doc.source, "JPMorgan")
        self.assertEqual(len(doc.themes), 1)
        self.assertEqual(doc.themes[0].label, "Higher term premium")
        self.assertEqual(len(doc.trades), 1)
        self.assertEqual(len(doc.assertions), 1)
        self.assertEqual(len(doc.world_nodes), 1)
        self.assertEqual(len(doc.world_edges), 1)
        self.assertEqual(len(doc.forecast_candidates), 1)
        self.assertEqual(len(doc.cross_document_references), 1)
        self.assertEqual(doc.cross_document_references[0].chunk_id, "chunk-1")

    def test_to_legacy_records_produces_expected_fields(self):
        """to_legacy_records() produces fields expected by synthesis/formatting."""
        analyst_batch = {
            "batch_key": "test-batch",
            "analysis_version": "v1",
            "generated_at": "2026-04-13T10:00:00Z",
            "scope": {},
            "documents": [
                {
                    "document_key": "doc-001",
                    "document_name": "doc-001",
                    "research_id": 12345,
                    "document_hash": "hashabc123",
                    "source": "Test Source",
                    "source_date": "2026-04-10",
                    "publisher": "Test Publisher",
                    "region": "US",
                    "asset_focus": "rates",
                    "quality": {"score": 85},
                    "themes": [
                        {
                            "label": "Theme 1",
                            "context": "Context",
                            "strength": "Primary",
                            "confidence": "High",
                        }
                    ],
                    "trades": [
                        {
                            "text": "Trade text",
                            "conviction": "High",
                            "timeframe": "weeks",
                        }
                    ],
                    "assertions": [
                        {
                            "summary_text": "Assertion",
                            "assertion_type": "forecast",
                            "status": "proposed",
                            "chunk_order": 0,
                            "assertion_order": 0,
                        }
                    ],
                    "world_nodes": [{"node_key": "n1", "canonical_label": "Node 1"}],
                    "world_edges": [{"edge_key": "e1", "edge_type": "drives"}],
                    "forecast_candidates": [],
                    "thesis": "Test thesis",
                    "contrarian_view": "Contrarian",
                    "recommended_positioning": "Position",
                    "cross_document_references": [
                        {
                            "chunk_id": "chunk-1",
                            "source_path": "/tmp/doc-a.pdf",
                            "source_date": "2026-04-09",
                            "text": "Supporting passage",
                            "relevance_score": 0.82,
                        }
                    ],
                }
            ],
            "cross_document_signals": {},
        }

        batch = DispatchBatch.from_dict(analyst_batch)
        legacy_records = batch.to_legacy_records()

        self.assertEqual(len(legacy_records), 1)
        record = legacy_records[0]

        self.assertEqual(record["id"], 12345)
        self.assertEqual(record["document_hash"], "hashabc123")
        self.assertIn("parsed_data", record)
        self.assertIn("themes", record["parsed_data"])
        self.assertIn("trades", record["parsed_data"])
        self.assertIn("metadata", record["parsed_data"])
        self.assertEqual(record["parsed_data"]["metadata"]["region"], "US")
        self.assertEqual(record["parsed_data"]["metadata"]["asset_focus"], "rates")
        self.assertEqual(record["cross_document_references"][0]["chunk_id"], "chunk-1")

    def test_analyst_export_roundtrip_integration(self):
        """Full round-trip: analyst export JSON → dispatcher ingestion."""
        analyst_export = {
            "batch_key": "integration-test",
            "analysis_version": "v1",
            "generated_at": "2026-04-13T12:00:00Z",
            "scope": {"document_keys": ["doc-1", "doc-2"]},
            "documents": [
                {
                    "document_key": "doc-1",
                    "document_name": "doc-1",
                    "research_id": 100,
                    "document_hash": "hash1",
                    "source": "Source A",
                    "source_date": "2026-04-01",
                    "publisher": "Pub A",
                    "region": "US",
                    "asset_focus": "rates",
                    "quality": {"score": 90},
                    "themes": [
                        {
                            "label": "Theme A",
                            "context": "Ctx",
                            "strength": "Primary",
                            "confidence": "High",
                        }
                    ],
                    "trades": [
                        {
                            "text": "Trade A",
                            "conviction": "Medium",
                            "timeframe": "months",
                        }
                    ],
                    "assertions": [],
                    "world_nodes": [],
                    "world_edges": [],
                    "forecast_candidates": [],
                    "thesis": "Thesis A",
                    "contrarian_view": "Contrarian A",
                    "recommended_positioning": "Position A",
                },
                {
                    "document_key": "doc-2",
                    "document_name": "doc-2",
                    "research_id": 101,
                    "document_hash": "hash2",
                    "source": "Source B",
                    "source_date": "2026-04-02",
                    "publisher": "Pub B",
                    "region": "EU",
                    "asset_focus": "equities",
                    "quality": {"score": 85},
                    "themes": [
                        {
                            "label": "Theme B",
                            "context": "Ctx",
                            "strength": "Secondary",
                            "confidence": "Medium",
                        }
                    ],
                    "trades": [
                        {"text": "Trade B", "conviction": "High", "timeframe": "weeks"}
                    ],
                    "assertions": [],
                    "world_nodes": [],
                    "world_edges": [],
                    "forecast_candidates": [],
                    "thesis": "Thesis B",
                    "contrarian_view": "Contrarian B",
                    "recommended_positioning": "Position B",
                },
            ],
            "cross_document_signals": {"common_themes": ["theme1"]},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(json.dumps(analyst_export))

            from src.analyst_client import AnalystBatchClient

            batch = AnalystBatchClient(path).load_batch()

            self.assertEqual(batch.batch_key, "integration-test")
            self.assertEqual(len(batch.documents), 2)
            self.assertEqual(batch.documents[0].research_id, 100)
            self.assertEqual(batch.documents[1].research_id, 101)
            self.assertEqual(batch.documents[0].region, "US")
            self.assertEqual(batch.documents[1].region, "EU")

            legacy = batch.to_legacy_records()
            self.assertEqual(len(legacy), 2)
            self.assertEqual(legacy[0]["parsed_data"]["metadata"]["region"], "US")
            self.assertEqual(legacy[1]["parsed_data"]["metadata"]["region"], "EU")


if __name__ == "__main__":
    unittest.main()
