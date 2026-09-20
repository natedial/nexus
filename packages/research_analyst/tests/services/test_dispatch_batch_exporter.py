"""Tests for dispatch batch exporter."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from research_analysis_layer.models.dispatch_scope import (
    DispatchScope,
    DispatchScopeError,
)
from research_analysis_layer.services.dispatch_batch_exporter import (
    DispatchBatchExporter,
)


class TestDispatchBatchExporter:
    """Test DispatchBatchExporter functionality."""

    def test_scope_validation_date_or_keys(self):
        """Test that scope requires either date bounds or document keys."""
        with pytest.raises(DispatchScopeError):
            scope = DispatchScope(batch_key="test")
            scope.validate_scope()

    def test_scope_validation_both(self):
        """Test that scope cannot have both date bounds and document keys."""
        with pytest.raises(DispatchScopeError):
            scope = DispatchScope(
                date_from=datetime.now(),
                document_keys=["doc1"],
                batch_key="test",
            )
            scope.validate_scope()

    def test_scope_validation_batch_key_required(self):
        """Test that batch_key is required."""
        with pytest.raises((DispatchScopeError, ValueError)):
            scope = DispatchScope(
                date_from=datetime.now(),
                date_to=datetime.now(),
            )

    def test_scope_valid_with_dates(self):
        """Test valid scope with date bounds."""
        scope = DispatchScope(
            date_from=datetime(2025, 1, 1),
            date_to=datetime(2025, 1, 31),
            batch_key="test-001",
        )
        scope.validate_scope()

    def test_scope_valid_with_keys(self):
        """Test valid scope with document keys."""
        scope = DispatchScope(
            document_keys=["doc1", "doc2"],
            batch_key="test-002",
        )
        scope.validate_scope()

    def test_scope_default_include_orphans(self):
        """Test that include_orphans defaults to True."""
        scope = DispatchScope(
            document_keys=["doc1"],
            batch_key="test",
        )
        assert scope.include_orphans is True

    def test_row_to_document_uses_nested_document_metadata(self):
        """Export rows preserve real document metadata from payload_json."""
        exporter = DispatchBatchExporter(MagicMock())
        row = {
            "document_key": "doc:123:hashabc",
            "research_id": 123,
            "document_hash": "hashabc",
            "thesis": "Top-level thesis",
            "payload_json": json.dumps(
                {
                    "quality": {"score": 0.9, "passed": True},
                    "themes": [{"label": "Rates"}],
                    "trades": [{"text": "Stay long duration"}],
                    "assertions": [{"summary_text": "Fed to cut"}],
                    "world_nodes": [{"node_key": "fed"}],
                    "world_edges": [{"edge_key": "fed-drives-rates"}],
                    "forecast_candidates": [{"indicator_key": "us_cpi"}],
                    "contrarian_view": "Counter-view",
                    "recommended_positioning": "Long duration",
                    "cross_document_references": [
                        {
                            "chunk_id": "chunk-1",
                            "source_path": "/tmp/doc.pdf",
                            "source_date": "2026-04-13",
                            "text": "Evidence",
                            "relevance_score": 0.8,
                        }
                    ],
                    "payload_json": {
                        "document": {
                            "file_id": "file-123",
                            "document_name": "real-doc-name.pdf",
                            "source": "Goldman Sachs",
                            "source_date": "2026-04-13",
                            "publisher": "Goldman Sachs",
                            "region": "US",
                            "asset_focus": "rates",
                            "document_link": "https://example.com/doc.pdf",
                        }
                    },
                }
            ),
        }

        document = exporter._row_to_document(row)

        assert document["document_name"] == "real-doc-name.pdf"
        assert document["file_id"] == "file-123"
        assert document["source"] == "Goldman Sachs"
        assert document["region"] == "US"
        assert document["asset_focus"] == "rates"
        assert document["document_link"] == "https://example.com/doc.pdf"
        assert document["cross_document_references"][0]["chunk_id"] == "chunk-1"
        assert document["argument_map"] == []
