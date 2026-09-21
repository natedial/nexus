"""Repository seam protocols for the analyst persistence layer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from research_analysis_layer.config import Settings
from research_analysis_layer.models import (
    AnalysisChunkDraft,
    AnalysisRun,
    AssertionDraft,
    EvidenceUnitDraft,
    ForecastCandidateDraft,
    ForecastCandidateRecord,
    ForecastExtractionSource,
    GraphUpdateResult,
    HydratedParsedDocument,
    NodeResolution,
    EdgeResolution,
)
from research_analysis_layer.models.consensus_shift_models import (
    ClusterState,
    ConsensusShiftEvent,
)
from research_analysis_layer.models.dispatch_scope import DispatchScope


@runtime_checkable
class AnalysisStoreProtocol(Protocol):
    """Persistence contract used by pipelines, tools, and dispatch export."""

    def create_run(
        self,
        run_type: str,
        trigger_source: str,
        settings: Settings,
        notes: str | None = None,
    ) -> AnalysisRun: ...

    def create_run_item(
        self,
        run_id: int,
        file_id: str,
        reason: str,
        research_id: int | None = None,
        document_hash: str | None = None,
        status: str = "queued",
    ) -> None: ...

    def replace_document_analysis(
        self,
        *,
        run_id: int,
        document: HydratedParsedDocument,
        chunks: list[AnalysisChunkDraft],
        evidence_units: list[EvidenceUnitDraft],
        assertions: list[AssertionDraft],
    ) -> None: ...

    def write_document_analysis(
        self,
        *,
        document_key: str,
        research_id: int,
        document_hash: str,
        analysis_version: str,
        run_id: str,
        payload_json: str,
        thesis: str | None = None,
        confidence: float | None = None,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        total_tool_calls: int | None = None,
        total_duration_ms: int | None = None,
    ) -> None: ...

    def list_document_analysis_for_dispatch(
        self,
        scope: DispatchScope,
    ) -> list[dict[str, Any]]: ...

    def list_argument_maps_for_consensus(
        self,
        *,
        limit: int | None = None,
    ) -> list[dict[str, object]]: ...

    def list_consensus_cluster_state(self) -> list[ClusterState]: ...

    def replace_consensus_cluster_state(self, clusters: list[ClusterState]) -> None: ...

    def insert_consensus_shift_events(
        self, events: list[ConsensusShiftEvent]
    ) -> int: ...

    def list_consensus_shift_events(
        self, *, limit: int | None = None
    ) -> list[dict[str, object]]: ...

    def write_shadow_street_digest(
        self,
        *,
        batch_key: str,
        generated_at: str,
        mode: str,
        payload_json: str,
    ) -> None: ...

    def load_shadow_street_digest(
        self, *, batch_key: str, generated_at: str
    ) -> dict[str, Any] | None: ...

    def get_analysis_counts(self) -> dict[str, int]: ...


def open_analysis_store(
    *,
    db_path: Path | None = None,
    database_url: str | None = None,
) -> AnalysisStoreProtocol:
    """Construct the configured analysis store backend."""
    from research_analysis_layer.db.analysis_store import AnalysisStore

    if database_url:
        return AnalysisStore(database_url=database_url)
    if db_path is None:
        raise ValueError("db_path is required when database_url is not set")
    return AnalysisStore(db_path=db_path)


def open_analysis_store_from_settings(settings: Settings) -> AnalysisStoreProtocol:
    if settings.analysis_database_url:
        return open_analysis_store(database_url=settings.analysis_database_url)
    return open_analysis_store(db_path=settings.analysis_db_path)
