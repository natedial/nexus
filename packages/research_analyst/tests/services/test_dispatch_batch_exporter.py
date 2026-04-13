"""Tests for dispatch batch exporter."""

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
