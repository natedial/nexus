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
            if scope.analysis_version:
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

                query += " AND analysis_version = ?"
                params.append(scope.analysis_version)

                query += " ORDER BY created_at ASC"
            else:
                subquery = """
                    SELECT document_hash, MAX(created_at) as max_created
                    FROM document_analysis
                    WHERE 1=1
                """
                subparams = []

                if scope.document_keys:
                    placeholders = ",".join("?" * len(scope.document_keys))
                    subquery += f" AND document_key IN ({placeholders})"
                    subparams.extend(scope.document_keys)
                else:
                    if scope.date_from:
                        subquery += " AND created_at >= ?"
                        subparams.append(scope.date_from.isoformat())
                    if scope.date_to:
                        subquery += " AND created_at < ?"
                        subparams.append(scope.date_to.isoformat())

                if not scope.include_orphans:
                    subquery += " AND research_id IS NOT NULL"

                subquery += " GROUP BY document_hash"

                query = f"""
                    SELECT da.* FROM document_analysis da
                    INNER JOIN ({subquery}) latest
                    ON da.document_hash = latest.document_hash
                    AND da.created_at = latest.max_created
                    ORDER BY da.created_at ASC
                """
                params = subparams

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
        row_dict = dict(row) if not isinstance(row, dict) else row
        analysis_payload = json.loads(row_dict["payload_json"])
        payload = (
            analysis_payload.get("payload_json", {})
            if isinstance(analysis_payload, dict)
            else {}
        )
        document_payload = (
            payload.get("document", {})
            if isinstance(payload.get("document"), dict)
            else {}
        )

        return {
            "document_key": row_dict["document_key"],
            "document_name": document_payload.get("document_name")
            or row_dict["document_key"],
            "research_id": row_dict["research_id"],
            "document_hash": row_dict["document_hash"],
            "file_id": document_payload.get("file_id"),
            "source": document_payload.get("source", ""),
            "source_date": document_payload.get("source_date", ""),
            "publisher": document_payload.get("publisher", ""),
            "region": document_payload.get("region", ""),
            "asset_focus": document_payload.get("asset_focus", ""),
            "document_link": document_payload.get("document_link", ""),
            "quality": analysis_payload.get("quality") or payload.get("quality", {}),
            "themes": analysis_payload.get("themes") or payload.get("themes", []),
            "trades": analysis_payload.get("trades") or payload.get("trades", []),
            "assertions": analysis_payload.get("assertions")
            or payload.get("assertions", []),
            "world_nodes": analysis_payload.get("world_nodes")
            or payload.get("world_nodes", []),
            "world_edges": analysis_payload.get("world_edges")
            or payload.get("world_edges", []),
            "forecast_candidates": analysis_payload.get("forecast_candidates")
            or payload.get("forecast_candidates", []),
            "thesis": row_dict.get("thesis", ""),
            "contrarian_view": analysis_payload.get("contrarian_view")
            or payload.get("contrarian_view", ""),
            "recommended_positioning": analysis_payload.get(
                "recommended_positioning"
            )
            or payload.get("recommended_positioning", ""),
            "cross_document_references": analysis_payload.get(
                "cross_document_references"
            )
            or payload.get("cross_document_references", []),
            "trading_opportunities": analysis_payload.get("trading_opportunities")
            or payload.get("trading_opportunities", []),
            "short_time_horizon_insights": analysis_payload.get(
                "short_time_horizon_insights"
            )
            or payload.get("short_time_horizon_insights", []),
            "talking_points": analysis_payload.get("talking_points")
            or payload.get("talking_points", []),
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
