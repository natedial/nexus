"""Export dispatch batches from document_analysis table."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_analysis_layer.models.dispatch_scope import (
    DispatchScope,
    DispatchScopeError,
)
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.services.street_digest import render_street_digest

logger = logging.getLogger(__name__)

_VALID_MODES = {"off", "shadow", "on"}


class DispatchBatchExporter:
    """Export DispatchBatch from document_analysis table.

    Produces a JSON file that the dispatcher can consume via AnalystBatchClient.
    Street-agrees rendering is gated by digest_consensus_mode (off/shadow/on).
    """

    def __init__(
        self,
        store: AnalysisStore,
        *,
        min_publishers: int = 2,
        consensus_mode: str = "off",
    ):
        if consensus_mode not in _VALID_MODES:
            raise ValueError(
                "digest consensus mode must be off, shadow, or on, "
                f"received {consensus_mode!r}"
            )
        self.store = store
        self.min_publishers = min_publishers
        self.consensus_mode = consensus_mode

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

        generated_at = datetime.now(timezone.utc).isoformat()
        return {
            "batch_key": scope.batch_key,
            "analysis_version": scope.analysis_version or "latest",
            "generated_at": generated_at,
            "scope": {
                "date_from": scope.date_from.isoformat() if scope.date_from else None,
                "date_to": scope.date_to.isoformat() if scope.date_to else None,
                "document_keys": scope.document_keys,
                "include_orphans": scope.include_orphans,
            },
            "documents": documents,
            "cross_document_signals": self._cross_document_signals(
                documents,
                batch_key=scope.batch_key,
                generated_at=generated_at,
            ),
        }

    def _cross_document_signals(
        self,
        documents: list[dict[str, Any]],
        *,
        batch_key: str,
        generated_at: str,
    ) -> dict[str, Any]:
        if self.consensus_mode == "off":
            return {}
        maps = [
            {
                "source": document.get("source"),
                "publisher": document.get("publisher"),
                "research_id": document.get("research_id"),
                "argument_map": document.get("argument_map") or [],
            }
            for document in documents
        ]
        section = render_street_digest(maps, min_publishers=self.min_publishers)
        payload = section.to_payload()
        if self.consensus_mode == "shadow":
            self.store.write_shadow_street_digest(
                batch_key=batch_key,
                generated_at=generated_at,
                mode=self.consensus_mode,
                payload_json=json.dumps(payload),
            )
            _emit_shadow_log(
                batch_key=batch_key,
                generated_at=generated_at,
                payload=payload,
            )
            return {}
        return {"street_agrees_splits": payload}

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
            "argument_map": analysis_payload.get("argument_map")
            or payload.get("argument_map")
            or [],
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


def _emit_shadow_log(
    *,
    batch_key: str,
    generated_at: str,
    payload: dict[str, Any],
) -> None:
    sys.stderr.write(
        json.dumps(
            {
                "event": "shadow_street_digest_complete",
                "batch_key": batch_key,
                "generated_at": generated_at,
                "agreement_count": payload.get("agreement_count", 0),
                "disagreement_count": payload.get("disagreement_count", 0),
                "reached_street_scale": payload.get("reached_street_scale", False),
            }
        )
        + "\n"
    )
