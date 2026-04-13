"""Export dispatch batches from document_analysis table."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from research_analysis_layer.models.dispatch_scope import (
    DispatchScope,
    DispatchScopeError,
)
from research_analysis_layer.db.analysis_store import AnalysisStore

logger = logging.getLogger(__name__)


class DispatchBatchExporter:
    """Export DispatchBatch from document_analysis table.

    Produces a JSON file that the dispatcher can consume via AnalystBatchClient.
    """

    def __init__(self, store: AnalysisStore):
        self.store = store

    def load_batch(self, scope: DispatchScope) -> dict[str, Any]:
        """Load a dispatch batch based on the given scope.

        Args:
            scope: DispatchScope defining what to export

        Returns:
            Dict representing the DispatchBatch

        Raises:
            DispatchScopeError: If scope is invalid
        """
        scope.validate_scope()

        with self.store._connect() as conn:
            query = "SELECT * FROM document_analysis WHERE 1=1"
            params = []

            if scope.document_keys:
                placeholders = ",".join("?" * len(scope.document_keys))
                query += f" AND document_key IN ({placeholders})"
                params.extend(scope.document_keys)
            else:
                if scope.date_from:
                    query += " AND created_at >= ?"
                    params.append(scope.date_from.isoformat())
                if scope.date_to:
                    query += " AND created_at < ?"
                    params.append(scope.date_to.isoformat())

            if not scope.include_orphans:
                query += " AND research_id IS NOT NULL"

            if scope.analysis_version:
                query += " AND analysis_version = ?"
                params.append(scope.analysis_version)

            query += " ORDER BY created_at ASC"

            rows = conn.execute(query, params).fetchall()

        documents = []
        for row in rows:
            doc = self._row_to_document(row)
            documents.append(doc)

        return {
            "batch_key": scope.batch_key,
            "analysis_version": scope.analysis_version or "latest",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": {
                "date_from": scope.date_from.isoformat() if scope.date_from else None,
                "date_to": scope.date_to.isoformat() if scope.date_to else None,
                "document_keys": scope.document_keys,
                "include_orphans": scope.include_orphans,
            },
            "documents": documents,
            "cross_document_signals": {},
        }

    def _row_to_document(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert a database row to a dispatch document."""
        payload = json.loads(row["payload_json"])

        return {
            "document_key": row["document_key"],
            "research_id": row["research_id"],
            "document_hash": row["document_hash"],
            "source": payload.get("source", ""),
            "source_date": payload.get("source_date", ""),
            "publisher": payload.get("publisher", ""),
            "region": payload.get("region", ""),
            "asset_focus": payload.get("asset_focus", ""),
            "document_link": payload.get("document_link", ""),
            "quality": payload.get("quality", {}),
            "themes": payload.get("themes", []),
            "trades": payload.get("trades", []),
            "assertions": payload.get("assertions", []),
            "world_nodes": payload.get("world_nodes", []),
            "world_edges": payload.get("world_edges", []),
            "forecast_candidates": payload.get("forecast_candidates", []),
            "thesis": row.get("thesis", ""),
            "contrarian_view": payload.get("contrarian_view", ""),
            "recommended_positioning": payload.get("recommended_positioning", ""),
            "cross_document_references": payload.get("cross_document_references", []),
            "trading_opportunities": payload.get("trading_opportunities", []),
            "short_time_horizon_insights": payload.get(
                "short_time_horizon_insights", []
            ),
            "talking_points": payload.get("talking_points", []),
        }

    def export_to_file(
        self,
        scope: DispatchScope,
        output_path: Path,
    ) -> None:
        """Export a dispatch batch to a JSON file.

        Args:
            scope: DispatchScope defining what to export
            output_path: Path to write the JSON file

        Raises:
            DispatchScopeError: If scope is invalid
        """
        batch = self.load_batch(scope)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(batch, f, indent=2, ensure_ascii=True)

        logger.info(
            "Exported batch %s with %d documents to %s",
            scope.batch_key,
            len(batch["documents"]),
            output_path,
        )


from datetime import timezone
