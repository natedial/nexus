"""SQLite-backed bootstrap analysis store."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from research_analysis_layer.clocks import utc_now
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


class AnalysisStore:
    """Bootstrap storage over local SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_source TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    chunker_version TEXT NOT NULL,
                    assertion_extractor_version TEXT NOT NULL,
                    resolver_version TEXT NOT NULL,
                    selected_watermark TEXT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    document_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_run_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    research_id INTEGER NULL,
                    document_hash TEXT NULL,
                    status TEXT NOT NULL,
                    selected_reason TEXT NOT NULL,
                    error_type TEXT NULL,
                    error_text TEXT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    assertion_count INTEGER NOT NULL DEFAULT 0,
                    node_upsert_count INTEGER NOT NULL DEFAULT 0,
                    edge_upsert_count INTEGER NOT NULL DEFAULT 0,
                    open_question_count INTEGER NOT NULL DEFAULT 0,
                    quality_score REAL NULL,
                    quality_summary_json TEXT NULL,
                    agent_success_count INTEGER NOT NULL DEFAULT 0,
                    agent_no_output_count INTEGER NOT NULL DEFAULT 0,
                    agent_error_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NULL,
                    UNIQUE(run_id, file_id)
                );

                CREATE TABLE IF NOT EXISTS analysis_documents (
                    research_id INTEGER PRIMARY KEY,
                    file_id TEXT NULL,
                    document_hash TEXT NOT NULL,
                    source TEXT NULL,
                    source_date TEXT NULL,
                    document_name TEXT NULL,
                    title TEXT NULL,
                    publisher TEXT NULL,
                    area TEXT NULL,
                    region TEXT NULL,
                    asset_focus TEXT NULL,
                    document_link TEXT NULL,
                    parser_updated_at TEXT NULL,
                    ingested_at TEXT NOT NULL,
                    last_analyzed_at TEXT NULL,
                    latest_analysis_version TEXT NULL,
                    latest_successful_run_id INTEGER NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    chunk_type TEXT NOT NULL,
                    section_name TEXT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    topic_tags_json TEXT NOT NULL,
                    entity_tags_json TEXT NOT NULL,
                    horizon_tag TEXT NULL,
                    parser_theme_id INTEGER NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_evidence_units (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    evidence_order INTEGER NOT NULL,
                    evidence_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NULL,
                    page_ref TEXT NULL,
                    source_ref_json TEXT NOT NULL,
                    parser_theme_id INTEGER NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order, evidence_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_assertions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    assertion_order INTEGER NOT NULL,
                    assertion_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    confidence_label TEXT NOT NULL,
                    extraction_confidence TEXT NOT NULL,
                    time_horizon TEXT NOT NULL,
                    time_anchor TEXT NULL,
                    condition_text TEXT NULL,
                    qualifier_text TEXT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    UNIQUE(research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_key TEXT NOT NULL UNIQUE,
                    node_type TEXT NOT NULL,
                    canonical_label TEXT NOT NULL,
                    summary_text TEXT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    support_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_node_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_key TEXT NOT NULL,
                    alias_key TEXT NOT NULL,
                    alias_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(node_key, alias_key)
                );

                CREATE TABLE IF NOT EXISTS world_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_key TEXT NOT NULL UNIQUE,
                    from_node_key TEXT NOT NULL,
                    to_node_key TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    directionality TEXT NOT NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    maturity TEXT NOT NULL,
                    support_count INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_node_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    evidence_text TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(node_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_edge_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    evidence_text TEXT NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(edge_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS world_edge_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    chunk_order INTEGER NULL,
                    assertion_order INTEGER NULL,
                    status TEXT NOT NULL,
                    authority_band TEXT NOT NULL,
                    maturity TEXT NOT NULL,
                    support_count INTEGER NOT NULL,
                    created_run_id INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(edge_key, research_id, document_hash, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS forecast_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    file_id TEXT NULL,
                    document_hash TEXT NULL,
                    source TEXT NULL,
                    source_date TEXT NULL,
                    document_name TEXT NULL,
                    document_link TEXT NULL,
                    chunk_order INTEGER NOT NULL,
                    assertion_order INTEGER NOT NULL,
                    assertion_text TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    indicator_key TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    country TEXT NULL,
                    period_text TEXT NULL,
                    release_date TEXT NULL,
                    forecast_type TEXT NOT NULL,
                    forecast_value_numeric REAL NULL,
                    forecast_value_low REAL NULL,
                    forecast_value_high REAL NULL,
                    forecast_value_text TEXT NOT NULL,
                    forecast_unit TEXT NULL,
                    qualifier_text TEXT NULL,
                    extraction_confidence TEXT NOT NULL,
                    match_status TEXT NOT NULL DEFAULT 'unmatched',
                    matched_economic_event_id TEXT NULL,
                    matched_calendar_release_id TEXT NULL,
                    matched_calendar_source TEXT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    review_notes TEXT NULL,
                    upload_status TEXT NOT NULL DEFAULT 'not_uploaded',
                    uploaded_at TEXT NULL,
                    created_run_id INTEGER NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, chunk_order, assertion_order)
                );

                CREATE TABLE IF NOT EXISTS analysis_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_scope TEXT NOT NULL,
                    review_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trading_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model_requested TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    error_type TEXT NULL,
                    error_text TEXT NULL,
                    opportunities_json TEXT NOT NULL DEFAULT '[]',
                    no_opportunity_reason TEXT NULL,
                    analyzed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version, agent_type)
                );

                CREATE TABLE IF NOT EXISTS short_time_horizon_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model_requested TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    error_type TEXT NULL,
                    error_text TEXT NULL,
                    insights_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NULL,
                    analyzed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version, agent_type)
                );

                CREATE TABLE IF NOT EXISTS talking_points_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    model_requested TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    error_type TEXT NULL,
                    error_text TEXT NULL,
                    talking_points_json TEXT NOT NULL DEFAULT '[]',
                    primary_headline TEXT NULL,
                    analyzed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version, agent_type)
                );

                CREATE TABLE IF NOT EXISTS document_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_key TEXT NOT NULL,
                    research_id INTEGER NOT NULL,
                    document_hash TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    thesis TEXT,
                    confidence REAL,
                    total_input_tokens INTEGER,
                    total_output_tokens INTEGER,
                    total_tool_calls INTEGER,
                    total_duration_ms INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(research_id, document_hash, analysis_version)
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_runs_completed_at
                    ON analysis_runs(completed_at);
                CREATE INDEX IF NOT EXISTS idx_analysis_run_items_run_id
                    ON analysis_run_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_analysis_documents_hash
                    ON analysis_documents(document_hash);
                CREATE INDEX IF NOT EXISTS idx_analysis_chunks_doc
                    ON analysis_chunks(research_id, document_hash);
                CREATE INDEX IF NOT EXISTS idx_analysis_assertions_doc
                    ON analysis_assertions(research_id, document_hash);
                CREATE INDEX IF NOT EXISTS idx_world_node_evidence_node_key
                    ON world_node_evidence(node_key);
                CREATE INDEX IF NOT EXISTS idx_world_edge_evidence_edge_key
                    ON world_edge_evidence(edge_key);
                CREATE INDEX IF NOT EXISTS idx_world_edge_history_edge_key
                    ON world_edge_history(edge_key);
                CREATE INDEX IF NOT EXISTS idx_forecast_candidates_review_status
                    ON forecast_candidates(review_status);
                CREATE INDEX IF NOT EXISTS idx_forecast_candidates_indicator_release
                    ON forecast_candidates(indicator_key, release_date);
                CREATE INDEX IF NOT EXISTS idx_analysis_reviews_scope_key
                    ON analysis_reviews(review_scope, review_key);
                CREATE INDEX IF NOT EXISTS idx_trading_analysis_lookup
                    ON trading_analysis(research_id, document_hash, analysis_version);
                CREATE INDEX IF NOT EXISTS idx_short_time_horizon_analysis_lookup
                    ON short_time_horizon_analysis(research_id, document_hash, analysis_version);
                CREATE INDEX IF NOT EXISTS idx_talking_points_analysis_lookup
                    ON talking_points_analysis(research_id, document_hash, analysis_version);
                CREATE INDEX IF NOT EXISTS document_analysis_research_id_idx
                    ON document_analysis(research_id);
                CREATE INDEX IF NOT EXISTS document_analysis_document_hash_idx
                    ON document_analysis(document_hash);
                """
            )
            self._ensure_column(
                conn, "analysis_run_items", "quality_score", "REAL NULL"
            )
            self._ensure_column(
                conn,
                "analysis_run_items",
                "quality_summary_json",
                "TEXT NULL",
            )
            self._ensure_column(
                conn,
                "analysis_run_items",
                "agent_success_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                "analysis_run_items",
                "agent_no_output_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                "analysis_run_items",
                "agent_error_count",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                conn,
                "forecast_candidates",
                "matched_calendar_release_id",
                "TEXT NULL",
            )
            self._ensure_column(
                conn,
                "forecast_candidates",
                "matched_calendar_source",
                "TEXT NULL",
            )
            self._ensure_column(conn, "analysis_run_items", "round_name", "TEXT NULL")
            self._ensure_column(conn, "analysis_run_items", "agent_name", "TEXT NULL")
            self._ensure_column(
                conn, "analysis_run_items", "tool_call_count", "INTEGER NULL"
            )
            self._ensure_column(
                conn, "analysis_run_items", "input_tokens", "INTEGER NULL"
            )
            self._ensure_column(
                conn, "analysis_run_items", "output_tokens", "INTEGER NULL"
            )
            self._ensure_column(conn, "analysis_run_items", "stop_reason", "TEXT NULL")

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row["name"] for row in rows}
        if column_name not in existing:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
            )

    def create_run(
        self,
        run_type: str,
        trigger_source: str,
        settings: Settings,
        notes: str | None = None,
    ) -> AnalysisRun:
        now = utc_now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_runs (
                    run_type,
                    status,
                    trigger_source,
                    analysis_version,
                    chunker_version,
                    assertion_extractor_version,
                    resolver_version,
                    started_at,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_type,
                    "running",
                    trigger_source,
                    settings.analysis_version,
                    settings.chunker_version,
                    settings.assertion_extractor_version,
                    settings.resolver_version,
                    now,
                    notes,
                ),
            )
            run_id = int(cursor.lastrowid)
        return AnalysisRun(
            id=run_id,
            run_type=run_type,
            status="running",
            trigger_source=trigger_source,
            analysis_version=settings.analysis_version,
            chunker_version=settings.chunker_version,
            assertion_extractor_version=settings.assertion_extractor_version,
            resolver_version=settings.resolver_version,
            started_at=datetime.fromisoformat(now),
        )

    def create_run_item(
        self,
        run_id: int,
        file_id: str,
        reason: str,
        research_id: int | None = None,
        document_hash: str | None = None,
        status: str = "queued",
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_run_items (
                    run_id,
                    file_id,
                    research_id,
                    document_hash,
                    status,
                    selected_reason,
                    started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, file_id, research_id, document_hash, status, reason, now),
            )

    def mark_run_item_processing(
        self,
        run_id: int,
        file_id: str,
        research_id: int | None,
        document_hash: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_run_items
                SET status = 'processing',
                    research_id = ?,
                    document_hash = ?
                WHERE run_id = ? AND file_id = ?
                """,
                (research_id, document_hash, run_id, file_id),
            )

    def finalize_run_item(
        self,
        run_id: int,
        file_id: str,
        status: str,
        *,
        research_id: int | None = None,
        document_hash: str | None = None,
        chunk_count: int = 0,
        assertion_count: int = 0,
        node_upsert_count: int = 0,
        edge_upsert_count: int = 0,
        open_question_count: int = 0,
        quality_score: float | None = None,
        quality_summary_json: str | None = None,
        agent_success_count: int = 0,
        agent_no_output_count: int = 0,
        agent_error_count: int = 0,
        error_type: str | None = None,
        error_text: str | None = None,
    ) -> None:
        completed_at = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_run_items
                SET status = ?,
                    research_id = COALESCE(?, research_id),
                    document_hash = COALESCE(?, document_hash),
                    chunk_count = ?,
                    assertion_count = ?,
                    node_upsert_count = ?,
                    edge_upsert_count = ?,
                    open_question_count = ?,
                    quality_score = ?,
                    quality_summary_json = ?,
                    agent_success_count = ?,
                    agent_no_output_count = ?,
                    agent_error_count = ?,
                    error_type = ?,
                    error_text = ?,
                    completed_at = ?
                WHERE run_id = ? AND file_id = ?
                """,
                (
                    status,
                    research_id,
                    document_hash,
                    chunk_count,
                    assertion_count,
                    node_upsert_count,
                    edge_upsert_count,
                    open_question_count,
                    quality_score,
                    quality_summary_json,
                    agent_success_count,
                    agent_no_output_count,
                    agent_error_count,
                    error_type,
                    error_text,
                    completed_at,
                    run_id,
                    file_id,
                ),
            )

    def get_latest_successful_watermark(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT selected_watermark
                FROM analysis_runs
                WHERE status IN ('success', 'partial_success')
                  AND selected_watermark IS NOT NULL
                ORDER BY completed_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None or row["selected_watermark"] is None:
            return None
        return datetime.fromisoformat(row["selected_watermark"])

    def get_document_version_status(
        self,
        research_id: int,
        document_hash: str,
        analysis_version: str,
    ) -> tuple[bool, str | None]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT document_hash, latest_analysis_version
                FROM analysis_documents
                WHERE research_id = ?
                """,
                (research_id,),
            ).fetchone()
        if row is None:
            return False, None
        same_hash = row["document_hash"] == document_hash
        same_version = row["latest_analysis_version"] == analysis_version
        return same_hash and same_version, row["document_hash"]

    def replace_document_analysis(
        self,
        run_id: int,
        parser_updated_at: datetime,
        document: HydratedParsedDocument,
        chunks: list[AnalysisChunkDraft],
        evidence_units: list[EvidenceUnitDraft],
        assertions: list[AssertionDraft],
    ) -> None:
        doc = document.document
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analysis_documents (
                    research_id,
                    file_id,
                    document_hash,
                    source,
                    source_date,
                    document_name,
                    title,
                    publisher,
                    area,
                    region,
                    asset_focus,
                    document_link,
                    parser_updated_at,
                    ingested_at,
                    last_analyzed_at,
                    latest_analysis_version,
                    latest_successful_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(research_id) DO UPDATE SET
                    file_id = excluded.file_id,
                    document_hash = excluded.document_hash,
                    source = excluded.source,
                    source_date = excluded.source_date,
                    document_name = excluded.document_name,
                    title = excluded.title,
                    publisher = excluded.publisher,
                    area = excluded.area,
                    region = excluded.region,
                    asset_focus = excluded.asset_focus,
                    document_link = excluded.document_link,
                    parser_updated_at = excluded.parser_updated_at,
                    last_analyzed_at = excluded.last_analyzed_at,
                    latest_analysis_version = excluded.latest_analysis_version,
                    latest_successful_run_id = excluded.latest_successful_run_id
                """,
                (
                    doc.id,
                    document.file_id,
                    doc.document_hash,
                    doc.source,
                    doc.source_date,
                    doc.document_name,
                    doc.document_title,
                    doc.publisher,
                    doc.area,
                    doc.region,
                    doc.asset_focus,
                    doc.document_link,
                    parser_updated_at.isoformat(),
                    now,
                    now,
                    None,
                    run_id,
                ),
            )
            conn.execute(
                "DELETE FROM analysis_chunks WHERE research_id = ? AND document_hash = ?",
                (doc.id, doc.document_hash),
            )
            conn.execute(
                "DELETE FROM analysis_evidence_units WHERE research_id = ? AND document_hash = ?",
                (doc.id, doc.document_hash),
            )
            conn.execute(
                "DELETE FROM analysis_assertions WHERE research_id = ? AND document_hash = ?",
                (doc.id, doc.document_hash),
            )

            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO analysis_chunks (
                        research_id,
                        document_hash,
                        chunk_order,
                        chunk_type,
                        section_name,
                        title,
                        text,
                        topic_tags_json,
                        entity_tags_json,
                        horizon_tag,
                        parser_theme_id,
                        created_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.id,
                        doc.document_hash,
                        chunk.chunk_order,
                        chunk.chunk_type,
                        chunk.section_name,
                        chunk.title,
                        chunk.text,
                        json.dumps(chunk.topic_tags),
                        json.dumps(chunk.entity_tags),
                        chunk.horizon_tag,
                        chunk.parser_theme_id,
                        run_id,
                    ),
                )

            for evidence in evidence_units:
                conn.execute(
                    """
                    INSERT INTO analysis_evidence_units (
                        research_id,
                        document_hash,
                        chunk_order,
                        evidence_order,
                        evidence_type,
                        text,
                        normalized_text,
                        page_ref,
                        source_ref_json,
                        parser_theme_id,
                        created_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.id,
                        doc.document_hash,
                        evidence.chunk_order,
                        evidence.evidence_order,
                        evidence.evidence_type,
                        evidence.text,
                        evidence.normalized_text,
                        evidence.page_ref,
                        json.dumps(evidence.source_ref),
                        evidence.parser_theme_id,
                        run_id,
                    ),
                )

            for assertion in assertions:
                conn.execute(
                    """
                    INSERT INTO analysis_assertions (
                        research_id,
                        document_hash,
                        chunk_order,
                        assertion_order,
                        assertion_type,
                        text,
                        normalized_text,
                        summary_text,
                        polarity,
                        confidence_label,
                        extraction_confidence,
                        time_horizon,
                        time_anchor,
                        condition_text,
                        qualifier_text,
                        status,
                        authority_band,
                        created_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc.id,
                        doc.document_hash,
                        assertion.chunk_order,
                        assertion.assertion_order,
                        assertion.assertion_type,
                        assertion.text,
                        assertion.normalized_text,
                        assertion.summary_text,
                        assertion.polarity,
                        assertion.confidence_label,
                        assertion.extraction_confidence,
                        assertion.time_horizon,
                        assertion.time_anchor,
                        assertion.condition_text,
                        assertion.qualifier_text,
                        assertion.status,
                        assertion.authority_band,
                        run_id,
                    ),
                )

    def upsert_world_nodes(self, nodes: list[NodeResolution]) -> int:
        now = utc_now().isoformat()
        count = 0
        with self._connect() as conn:
            for node in nodes:
                conn.execute(
                    """
                    INSERT INTO world_nodes (
                        node_key,
                        node_type,
                        canonical_label,
                        summary_text,
                        status,
                        authority_band,
                        support_count,
                        created_at,
                        last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_key) DO UPDATE SET
                        canonical_label = excluded.canonical_label,
                        summary_text = excluded.summary_text,
                        status = excluded.status,
                        authority_band = excluded.authority_band,
                        support_count = world_nodes.support_count + excluded.support_count,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        node.node_key,
                        node.node_type,
                        node.canonical_label,
                        node.summary_text,
                        node.status,
                        node.authority_band,
                        node.support_count,
                        now,
                        now,
                    ),
                )
                count += 1
        return count

    def upsert_world_edges(self, edges: list[EdgeResolution]) -> int:
        now = utc_now().isoformat()
        count = 0
        with self._connect() as conn:
            for edge in edges:
                conn.execute(
                    """
                    INSERT INTO world_edges (
                        edge_key,
                        from_node_key,
                        to_node_key,
                        edge_type,
                        directionality,
                        status,
                        authority_band,
                        maturity,
                        support_count,
                        created_at,
                        last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(edge_key) DO UPDATE SET
                        status = excluded.status,
                        authority_band = excluded.authority_band,
                        maturity = excluded.maturity,
                        support_count = world_edges.support_count + excluded.support_count,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        edge.edge_key,
                        edge.from_node_key,
                        edge.to_node_key,
                        edge.edge_type,
                        edge.directionality,
                        edge.status,
                        edge.authority_band,
                        edge.maturity,
                        edge.support_count,
                        now,
                        now,
                    ),
                )
                count += 1
        return count

    def record_graph_provenance(
        self,
        *,
        run_id: int,
        research_id: int,
        document_hash: str,
        nodes: list[NodeResolution],
        edges: list[EdgeResolution],
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            for node in nodes:
                if node.alias_text:
                    alias_key = node.alias_text.casefold().strip()
                    conn.execute(
                        """
                        INSERT INTO world_node_aliases (
                            node_key,
                            alias_key,
                            alias_text,
                            created_at,
                            last_seen_at
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(node_key, alias_key) DO UPDATE SET
                            alias_text = excluded.alias_text,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (node.node_key, alias_key, node.alias_text, now, now),
                    )
                if node.evidence_text:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO world_node_evidence (
                            node_key,
                            research_id,
                            document_hash,
                            chunk_order,
                            assertion_order,
                            evidence_text,
                            created_run_id,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            node.node_key,
                            research_id,
                            document_hash,
                            node.chunk_order,
                            node.assertion_order,
                            node.evidence_text,
                            run_id,
                            now,
                        ),
                    )
            for edge in edges:
                if edge.evidence_text:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO world_edge_evidence (
                            edge_key,
                            research_id,
                            document_hash,
                            chunk_order,
                            assertion_order,
                            evidence_text,
                            created_run_id,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            edge.edge_key,
                            research_id,
                            document_hash,
                            edge.chunk_order,
                            edge.assertion_order,
                            edge.evidence_text,
                            run_id,
                            now,
                        ),
                    )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO world_edge_history (
                        edge_key,
                        research_id,
                        document_hash,
                        chunk_order,
                        assertion_order,
                        status,
                        authority_band,
                        maturity,
                        support_count,
                        created_run_id,
                        recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.edge_key,
                        research_id,
                        document_hash,
                        edge.chunk_order,
                        edge.assertion_order,
                        edge.status,
                        edge.authority_band,
                        edge.maturity,
                        edge.support_count,
                        run_id,
                        now,
                    ),
                )

    def refresh_world_node_lifecycle(self, node_keys: list[str] | None = None) -> int:
        predicate = ""
        params: list[object] = []
        if node_keys:
            placeholders = ",".join("?" for _ in node_keys)
            predicate = f" WHERE node_key IN ({placeholders})"
            params.extend(node_keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT node_key, support_count
                FROM world_nodes
                {predicate}
                """,
                params,
            ).fetchall()
            for row in rows:
                support_count = int(row["support_count"])
                status = (
                    "reinforced"
                    if support_count >= 3
                    else "supported"
                    if support_count >= 2
                    else "proposed"
                )
                authority_band = (
                    "core"
                    if support_count >= 8
                    else "established"
                    if support_count >= 5
                    else "emerging"
                    if support_count >= 3
                    else "seed"
                )
                conn.execute(
                    """
                    UPDATE world_nodes
                    SET status = ?, authority_band = ?
                    WHERE node_key = ?
                    """,
                    (status, authority_band, row["node_key"]),
                )
        return len(rows)

    def refresh_world_edge_lifecycle(self, edge_keys: list[str] | None = None) -> int:
        predicate = ""
        params: list[object] = []
        if edge_keys:
            placeholders = ",".join("?" for _ in edge_keys)
            predicate = f" WHERE edge_key IN ({placeholders})"
            params.extend(edge_keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT edge_key, support_count
                FROM world_edges
                {predicate}
                """,
                params,
            ).fetchall()
            for row in rows:
                support_count = int(row["support_count"])
                status = (
                    "reinforced"
                    if support_count >= 3
                    else "supported"
                    if support_count >= 2
                    else "proposed"
                )
                authority_band = (
                    "structural"
                    if support_count >= 8
                    else "established"
                    if support_count >= 5
                    else "emerging"
                    if support_count >= 3
                    else "seed"
                )
                maturity = (
                    "highway"
                    if support_count >= 8
                    else "road"
                    if support_count >= 5
                    else "path"
                    if support_count >= 3
                    else "trace"
                )
                conn.execute(
                    """
                    UPDATE world_edges
                    SET status = ?, authority_band = ?, maturity = ?
                    WHERE edge_key = ?
                    """,
                    (status, authority_band, maturity, row["edge_key"]),
                )
        return len(rows)

    def set_document_analysis_version(
        self,
        research_id: int,
        analysis_version: str,
        run_id: int,
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_documents
                SET latest_analysis_version = ?,
                    latest_successful_run_id = ?,
                    last_analyzed_at = ?
                WHERE research_id = ?
                """,
                (analysis_version, run_id, now, research_id),
            )

    def finalize_run(
        self,
        run_id: int,
        selected_watermark: datetime | None,
    ) -> dict[str, int | str | None]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status FROM analysis_run_items WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        statuses = [row["status"] for row in rows]
        success_count = statuses.count("success")
        skipped_count = sum(1 for status in statuses if status.startswith("skipped_"))
        error_count = statuses.count("error")
        if error_count and success_count:
            status = "partial_success"
        elif error_count:
            status = "error"
        else:
            status = "success"
        completed_at = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE analysis_runs
                SET status = ?,
                    completed_at = ?,
                    document_count = ?,
                    success_count = ?,
                    skipped_count = ?,
                    error_count = ?,
                    selected_watermark = ?
                WHERE id = ?
                """,
                (
                    status,
                    completed_at,
                    len(statuses),
                    success_count,
                    skipped_count,
                    error_count,
                    selected_watermark.isoformat() if selected_watermark else None,
                    run_id,
                ),
            )
        return {
            "status": status,
            "document_count": len(statuses),
            "success_count": success_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
        }

    def get_forecast_extraction_sources(
        self,
        *,
        limit: int | None = None,
        research_id: int | None = None,
        only_missing: bool = True,
    ) -> list[ForecastExtractionSource]:
        query = """
            SELECT
                d.research_id,
                d.file_id,
                d.document_hash,
                d.source,
                d.source_date,
                d.document_name,
                d.document_link,
                a.chunk_order,
                a.assertion_order,
                a.text AS assertion_text,
                a.summary_text,
                COALESCE(NULLIF(group_concat(e.text, ' '), ''), c.text, a.text) AS evidence_text,
                a.qualifier_text,
                a.extraction_confidence,
                a.created_run_id
            FROM analysis_assertions a
            JOIN analysis_documents d
              ON d.research_id = a.research_id
             AND d.document_hash = a.document_hash
            JOIN analysis_chunks c
              ON c.research_id = a.research_id
             AND c.document_hash = a.document_hash
             AND c.chunk_order = a.chunk_order
            LEFT JOIN analysis_evidence_units e
              ON e.research_id = a.research_id
             AND e.document_hash = a.document_hash
             AND e.chunk_order = a.chunk_order
        """
        params: list[object] = []
        if only_missing:
            query += """
            LEFT JOIN forecast_candidates f
              ON f.research_id = a.research_id
             AND f.chunk_order = a.chunk_order
             AND f.assertion_order = a.assertion_order
            """
        query += """
            WHERE a.assertion_type = 'forecast'
        """
        if only_missing:
            query += " AND f.id IS NULL"
        if research_id is not None:
            query += " AND a.research_id = ?"
            params.append(research_id)
        query += """
            GROUP BY
                d.research_id,
                d.file_id,
                d.document_hash,
                d.source,
                d.source_date,
                d.document_name,
                d.document_link,
                a.chunk_order,
                a.assertion_order,
                a.text,
                a.summary_text,
                c.text,
                a.qualifier_text,
                a.extraction_confidence,
                a.created_run_id
            ORDER BY d.source_date DESC, d.research_id DESC, a.chunk_order ASC
        """
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            ForecastExtractionSource(
                research_id=int(row["research_id"]),
                file_id=row["file_id"],
                document_hash=row["document_hash"],
                source=row["source"],
                source_date=row["source_date"],
                document_name=row["document_name"],
                document_link=row["document_link"],
                chunk_order=int(row["chunk_order"]),
                assertion_order=int(row["assertion_order"]),
                assertion_text=row["assertion_text"],
                summary_text=row["summary_text"],
                evidence_text=row["evidence_text"] or row["assertion_text"],
                qualifier_text=row["qualifier_text"],
                extraction_confidence=row["extraction_confidence"] or "medium",
                created_run_id=int(row["created_run_id"]),
            )
            for row in rows
        ]

    def upsert_forecast_candidates(
        self,
        candidates: list[ForecastCandidateDraft],
    ) -> int:
        if not candidates:
            return 0
        now = utc_now().isoformat()
        with self._connect() as conn:
            for candidate in candidates:
                conn.execute(
                    """
                    INSERT INTO forecast_candidates (
                        research_id,
                        file_id,
                        document_hash,
                        source,
                        source_date,
                        document_name,
                        document_link,
                        chunk_order,
                        assertion_order,
                        assertion_text,
                        summary_text,
                        evidence_text,
                        indicator_key,
                        event_name,
                        country,
                        period_text,
                        release_date,
                        forecast_type,
                        forecast_value_numeric,
                        forecast_value_low,
                        forecast_value_high,
                        forecast_value_text,
                        forecast_unit,
                        qualifier_text,
                        extraction_confidence,
                        match_status,
                        matched_economic_event_id,
                        matched_calendar_release_id,
                        matched_calendar_source,
                        review_status,
                        review_notes,
                        upload_status,
                        uploaded_at,
                        created_run_id,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(research_id, chunk_order, assertion_order) DO UPDATE SET
                        file_id = excluded.file_id,
                        document_hash = excluded.document_hash,
                        source = excluded.source,
                        source_date = excluded.source_date,
                        document_name = excluded.document_name,
                        document_link = excluded.document_link,
                        assertion_text = excluded.assertion_text,
                        summary_text = excluded.summary_text,
                        evidence_text = excluded.evidence_text,
                        indicator_key = excluded.indicator_key,
                        event_name = excluded.event_name,
                        country = excluded.country,
                        period_text = excluded.period_text,
                        release_date = excluded.release_date,
                        forecast_type = excluded.forecast_type,
                        forecast_value_numeric = excluded.forecast_value_numeric,
                        forecast_value_low = excluded.forecast_value_low,
                        forecast_value_high = excluded.forecast_value_high,
                        forecast_value_text = excluded.forecast_value_text,
                        forecast_unit = excluded.forecast_unit,
                        qualifier_text = excluded.qualifier_text,
                        extraction_confidence = excluded.extraction_confidence,
                        match_status = excluded.match_status,
                        matched_economic_event_id = excluded.matched_economic_event_id,
                        matched_calendar_release_id = excluded.matched_calendar_release_id,
                        matched_calendar_source = excluded.matched_calendar_source,
                        review_status = excluded.review_status,
                        review_notes = excluded.review_notes,
                        upload_status = excluded.upload_status,
                        uploaded_at = excluded.uploaded_at,
                        created_run_id = excluded.created_run_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        candidate.research_id,
                        candidate.file_id,
                        candidate.document_hash,
                        candidate.source,
                        candidate.source_date,
                        candidate.document_name,
                        candidate.document_link,
                        candidate.chunk_order,
                        candidate.assertion_order,
                        candidate.assertion_text,
                        candidate.summary_text,
                        candidate.evidence_text,
                        candidate.indicator_key,
                        candidate.event_name,
                        candidate.country,
                        candidate.period_text,
                        candidate.release_date,
                        candidate.forecast_type,
                        candidate.forecast_value_numeric,
                        candidate.forecast_value_low,
                        candidate.forecast_value_high,
                        candidate.forecast_value_text,
                        candidate.forecast_unit,
                        candidate.qualifier_text,
                        candidate.extraction_confidence,
                        candidate.match_status,
                        candidate.matched_economic_event_id,
                        candidate.matched_calendar_release_id,
                        candidate.matched_calendar_source,
                        candidate.review_status,
                        candidate.review_notes,
                        candidate.upload_status,
                        None,
                        candidate.created_run_id,
                        now,
                        now,
                    ),
                )
        return len(candidates)

    def delete_forecast_candidates(self, research_id: int | None = None) -> int:
        with self._connect() as conn:
            if research_id is None:
                cursor = conn.execute("DELETE FROM forecast_candidates")
            else:
                cursor = conn.execute(
                    "DELETE FROM forecast_candidates WHERE research_id = ?",
                    (research_id,),
                )
        return int(cursor.rowcount)

    def list_forecast_candidates(
        self,
        *,
        candidate_ids: list[int] | None = None,
        review_status: str | None = None,
        upload_status: str | None = None,
        limit: int | None = None,
    ) -> list[ForecastCandidateRecord]:
        query = "SELECT * FROM forecast_candidates WHERE 1 = 1"
        params: list[object] = []
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            query += f" AND id IN ({placeholders})"
            params.extend(candidate_ids)
        if review_status:
            query += " AND review_status = ?"
            params.append(review_status)
        if upload_status:
            query += " AND upload_status = ?"
            params.append(upload_status)
        query += " ORDER BY source_date DESC, id ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._forecast_candidate_from_row(row) for row in rows]

    def list_analyzed_documents(
        self,
        *,
        limit: int | None = None,
        research_id: int | None = None,
    ) -> list[dict[str, object]]:
        query = """
            SELECT
                research_id,
                file_id,
                document_hash,
                source,
                source_date,
                document_name,
                document_link,
                latest_successful_run_id
            FROM analysis_documents
            WHERE 1 = 1
        """
        params: list[object] = []
        if research_id is not None:
            query += " AND research_id = ?"
            params.append(research_id)
        query += " ORDER BY source_date DESC, research_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def upsert_agent_result(self, agent_type: str, result) -> None:
        """Persist one agent execution result row."""

        metadata = result.metadata
        payload = (
            self._base_model_dump(result.payload) if result.payload is not None else {}
        )
        if agent_type == "trading_opportunities":
            self._upsert_agent_row(
                table_name="trading_analysis",
                metadata=metadata,
                status=result.status,
                error_type=result.error_type,
                error_text=result.error_text,
                payload_columns={
                    "opportunities_json": json.dumps(
                        payload.get("opportunities", []),
                        sort_keys=True,
                    ),
                    "no_opportunity_reason": payload.get("no_opportunity_reason"),
                },
            )
            return
        if agent_type == "short_time_horizon":
            self._upsert_agent_row(
                table_name="short_time_horizon_analysis",
                metadata=metadata,
                status=result.status,
                error_type=result.error_type,
                error_text=result.error_text,
                payload_columns={
                    "insights_json": json.dumps(
                        payload.get("insights", []),
                        sort_keys=True,
                    ),
                    "summary": payload.get("summary"),
                },
            )
            return
        if agent_type == "talking_points":
            self._upsert_agent_row(
                table_name="talking_points_analysis",
                metadata=metadata,
                status=result.status,
                error_type=result.error_type,
                error_text=result.error_text,
                payload_columns={
                    "talking_points_json": json.dumps(
                        payload.get("talking_points", []),
                        sort_keys=True,
                    ),
                    "primary_headline": payload.get("primary_headline"),
                },
            )
            return
        raise ValueError(f"unsupported agent type: {agent_type}")

    def _upsert_agent_row(
        self,
        *,
        table_name: str,
        metadata,
        status: str,
        error_type: str | None,
        error_text: str | None,
        payload_columns: dict[str, object],
    ) -> None:
        now = utc_now().isoformat()
        values = {
            "research_id": metadata.research_id,
            "document_hash": metadata.document_hash,
            "analysis_version": metadata.analysis_version,
            "agent_type": metadata.agent_type,
            "prompt_version": metadata.prompt_version,
            "model_requested": metadata.model_requested,
            "model_used": metadata.model_used,
            "run_id": metadata.run_id,
            "attempt_count": metadata.attempt_count,
            "status": status,
            "error_type": error_type,
            "error_text": error_text,
            "analyzed_at": metadata.analyzed_at.isoformat(),
            "created_at": now,
            "updated_at": now,
            **payload_columns,
        }
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_sql = ", ".join(
            f"{column} = excluded.{column}"
            for column in columns
            if column
            not in {
                "research_id",
                "document_hash",
                "analysis_version",
                "agent_type",
                "created_at",
            }
        )
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {table_name} (
                    {", ".join(columns)}
                ) VALUES ({placeholders})
                ON CONFLICT(research_id, document_hash, analysis_version, agent_type)
                DO UPDATE SET {update_sql}
                """,
                tuple(values[column] for column in columns),
            )

    def get_agent_result(
        self,
        *,
        table_name: str,
        research_id: int,
        document_hash: str,
        analysis_version: str,
    ) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT *
                FROM {table_name}
                WHERE research_id = ? AND document_hash = ? AND analysis_version = ?
                LIMIT 1
                """,
                (research_id, document_hash, analysis_version),
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _base_model_dump(model) -> dict[str, object]:
        dumper = getattr(model, "model_dump", None)
        if callable(dumper):
            return dumper()
        return model.dict()

    def update_forecast_review_status(
        self,
        *,
        candidate_ids: list[int],
        review_status: str,
        review_notes: str | None = None,
    ) -> int:
        if not candidate_ids:
            return 0
        placeholders = ",".join("?" for _ in candidate_ids)
        now = utc_now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE forecast_candidates
                SET review_status = ?,
                    review_notes = COALESCE(?, review_notes),
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                [review_status, review_notes, now, *candidate_ids],
            )
        return int(cursor.rowcount)

    def mark_forecast_upload_result(
        self,
        *,
        candidate_id: int,
        upload_status: str,
        review_status: str | None = None,
        review_notes: str | None = None,
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_candidates
                SET upload_status = ?,
                    uploaded_at = CASE WHEN ? = 'uploaded' THEN ? ELSE uploaded_at END,
                    review_status = COALESCE(?, review_status),
                    review_notes = COALESCE(?, review_notes),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    upload_status,
                    upload_status,
                    now,
                    review_status,
                    review_notes,
                    now,
                    candidate_id,
                ),
            )

    def save_review_snapshot(
        self,
        *,
        review_scope: str,
        review_key: str,
        payload: dict[str, object],
    ) -> int:
        now = utc_now().isoformat()
        payload_json = json.dumps(payload, sort_keys=True)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO analysis_reviews (
                    review_scope,
                    review_key,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (review_scope, review_key, payload_json, now),
            )
        return int(cursor.lastrowid)

    def build_document_review(
        self,
        *,
        research_id: int,
        document_hash: str | None = None,
    ) -> dict[str, object] | None:
        with self._connect() as conn:
            if document_hash is None:
                document_row = conn.execute(
                    """
                    SELECT *
                    FROM analysis_documents
                    WHERE research_id = ?
                    ORDER BY last_analyzed_at DESC
                    LIMIT 1
                    """,
                    (research_id,),
                ).fetchone()
            else:
                document_row = conn.execute(
                    """
                    SELECT *
                    FROM analysis_documents
                    WHERE research_id = ? AND document_hash = ?
                    LIMIT 1
                    """,
                    (research_id, document_hash),
                ).fetchone()
            if document_row is None:
                return None
            doc_hash = str(document_row["document_hash"])
            chunks = conn.execute(
                """
                SELECT chunk_order, chunk_type, section_name, title, text, topic_tags_json, entity_tags_json, horizon_tag
                FROM analysis_chunks
                WHERE research_id = ? AND document_hash = ?
                ORDER BY chunk_order ASC
                """,
                (research_id, doc_hash),
            ).fetchall()
            assertions = conn.execute(
                """
                SELECT chunk_order, assertion_order, assertion_type, summary_text, text, status, authority_band,
                       time_horizon, time_anchor, condition_text, qualifier_text
                FROM analysis_assertions
                WHERE research_id = ? AND document_hash = ?
                ORDER BY chunk_order ASC, assertion_order ASC
                """,
                (research_id, doc_hash),
            ).fetchall()
            node_rows = conn.execute(
                """
                SELECT DISTINCT n.node_key, n.node_type, n.canonical_label, n.status, n.authority_band, n.support_count
                FROM world_nodes n
                JOIN world_node_evidence e ON e.node_key = n.node_key
                WHERE e.research_id = ? AND e.document_hash = ?
                ORDER BY n.node_key ASC
                """,
                (research_id, doc_hash),
            ).fetchall()
            edge_rows = conn.execute(
                """
                SELECT DISTINCT w.edge_key, w.from_node_key, w.to_node_key, w.edge_type, w.status, w.authority_band,
                                w.maturity, w.support_count
                FROM world_edges w
                JOIN world_edge_evidence e ON e.edge_key = w.edge_key
                WHERE e.research_id = ? AND e.document_hash = ?
                ORDER BY w.edge_key ASC
                """,
                (research_id, doc_hash),
            ).fetchall()
            quality_row = conn.execute(
                """
                SELECT quality_score, quality_summary_json
                FROM analysis_run_items
                WHERE research_id = ? AND document_hash = ? AND quality_summary_json IS NOT NULL
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (research_id, doc_hash),
            ).fetchone()
        return {
            "document": dict(document_row),
            "quality": (
                {
                    "quality_score": quality_row["quality_score"],
                    "quality_summary": json.loads(quality_row["quality_summary_json"]),
                }
                if quality_row is not None and quality_row["quality_summary_json"]
                else None
            ),
            "chunks": [
                {
                    **dict(row),
                    "topic_tags": json.loads(row["topic_tags_json"]),
                    "entity_tags": json.loads(row["entity_tags_json"]),
                }
                for row in chunks
            ],
            "assertions": [dict(row) for row in assertions],
            "world_nodes": [dict(row) for row in node_rows],
            "world_edges": [dict(row) for row in edge_rows],
        }

    def get_analysis_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            tables = [
                "analysis_runs",
                "analysis_run_items",
                "analysis_documents",
                "analysis_chunks",
                "analysis_assertions",
                "trading_analysis",
                "short_time_horizon_analysis",
                "talking_points_analysis",
                "forecast_candidates",
                "analysis_reviews",
                "world_nodes",
                "world_edges",
            ]
            counts: dict[str, int] = {}
            for table in tables:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
                counts[table] = int(row["count"])
        return counts

    def has_analysis_for_document(
        self,
        research_id: int,
        document_hash: str | None,
        analysis_version: str,
    ) -> bool:
        """Return whether this parsed document version has been analyzed."""
        if not document_hash:
            return False
        processed, _ = self.get_document_version_status(
            research_id=research_id,
            document_hash=document_hash,
            analysis_version=analysis_version,
        )
        return processed

    @staticmethod
    def _forecast_candidate_from_row(row: sqlite3.Row) -> ForecastCandidateRecord:
        return ForecastCandidateRecord(
            id=int(row["id"]),
            research_id=int(row["research_id"]),
            file_id=row["file_id"],
            document_hash=row["document_hash"],
            source=row["source"],
            source_date=row["source_date"],
            document_name=row["document_name"],
            document_link=row["document_link"],
            chunk_order=int(row["chunk_order"]),
            assertion_order=int(row["assertion_order"]),
            assertion_text=row["assertion_text"],
            summary_text=row["summary_text"],
            evidence_text=row["evidence_text"],
            indicator_key=row["indicator_key"],
            event_name=row["event_name"],
            country=row["country"],
            period_text=row["period_text"],
            release_date=row["release_date"],
            forecast_type=row["forecast_type"],
            forecast_value_numeric=row["forecast_value_numeric"],
            forecast_value_low=row["forecast_value_low"],
            forecast_value_high=row["forecast_value_high"],
            forecast_value_text=row["forecast_value_text"],
            forecast_unit=row["forecast_unit"],
            qualifier_text=row["qualifier_text"],
            extraction_confidence=row["extraction_confidence"],
            match_status=row["match_status"],
            matched_economic_event_id=row["matched_economic_event_id"],
            matched_calendar_release_id=row["matched_calendar_release_id"],
            matched_calendar_source=row["matched_calendar_source"],
            review_status=row["review_status"],
            review_notes=row["review_notes"],
            upload_status=row["upload_status"],
            uploaded_at=row["uploaded_at"],
            created_run_id=row["created_run_id"],
        )

    def write_document_analysis(
        self,
        *,
        document_key: str,
        research_id: int,
        document_hash: str,
        analysis_version: str,
        run_id: str,
        payload_json: str,
        thesis: str | None,
        confidence: float | None,
        total_input_tokens: int,
        total_output_tokens: int,
        total_tool_calls: int,
        total_duration_ms: int,
    ) -> None:
        """Write or update a document analysis record.

        Uses idempotent upsert on (research_id, document_hash, analysis_version).
        """
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_analysis (
                    document_key, research_id, document_hash, analysis_version,
                    run_id, payload_json, thesis, confidence,
                    total_input_tokens, total_output_tokens, total_tool_calls,
                    total_duration_ms, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(research_id, document_hash, analysis_version) DO UPDATE SET
                    run_id = excluded.run_id,
                    payload_json = excluded.payload_json,
                    thesis = excluded.thesis,
                    confidence = excluded.confidence,
                    total_input_tokens = excluded.total_input_tokens,
                    total_output_tokens = excluded.total_output_tokens,
                    total_tool_calls = excluded.total_tool_calls,
                    total_duration_ms = excluded.total_duration_ms,
                    updated_at = excluded.updated_at
                """,
                (
                    document_key,
                    research_id,
                    document_hash,
                    analysis_version,
                    run_id,
                    payload_json,
                    thesis,
                    confidence,
                    total_input_tokens,
                    total_output_tokens,
                    total_tool_calls,
                    total_duration_ms,
                    now,
                    now,
                ),
            )
