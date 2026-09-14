"""Run and selection models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ParserStateRecord:
    """One completed parser state row."""

    file_id: str
    file_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    parse_ok: bool | None = None
    boilerplate_ok: bool | None = None
    metadata_ok: bool | None = None
    themes_ok: bool | None = None
    trades_ok: bool | None = None
    storage_ok: bool | None = None
    error_message: str | None = None


@dataclass(slots=True)
class SelectionDecision:
    """Selection result for one upstream document."""

    file_id: str
    file_name: str
    selected: bool
    status: str
    reason: str
    research_id: int | None = None
    document_hash: str | None = None


@dataclass(slots=True)
class AnalysisRun:
    """Persisted analysis run."""

    id: int
    run_type: str
    status: str
    trigger_source: str
    analysis_version: str
    chunker_version: str
    assertion_extractor_version: str
    resolver_version: str
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(slots=True)
class RunItemResult:
    """Per-document result for the pipeline."""

    status: str
    chunk_count: int = 0
    assertion_count: int = 0
    node_upsert_count: int = 0
    edge_upsert_count: int = 0
    open_question_count: int = 0
    error_type: str | None = None
    error_text: str | None = None
    quality_score: float | None = None
    quality_summary_json: str | None = None
    agent_success_count: int = 0
    agent_no_output_count: int = 0
    agent_error_count: int = 0
