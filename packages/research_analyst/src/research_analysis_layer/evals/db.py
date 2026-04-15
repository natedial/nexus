"""Database schema and operations for eval infrastructure."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVAL_SCHEMA = """
-- Table: agent_eval_runs
CREATE TABLE IF NOT EXISTS agent_eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Schema validation
    schema_valid BOOLEAN NOT NULL,
    
    -- Field-level scores
    thesis_similarity REAL,
    claims_similarity REAL,
    trades_similarity REAL,
    talking_points_similarity REAL,
    confidence_similarity REAL,
    confidence REAL,
    
    -- LLM judge scores
    judge_thesis_clarity REAL,
    judge_claim_grounding REAL,
    judge_trading_actionability REAL,
    judge_talking_point_quality REAL,
    judge_coherence REAL,
    judge_reasoning TEXT,
    
    -- Metadata
    latency_ms INTEGER,
    model_used TEXT,
    prompt_version TEXT,
    
    UNIQUE(run_id, document_id, agent_type)
);

-- Table: training_captures
CREATE TABLE IF NOT EXISTS training_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT UNIQUE NOT NULL,
    document_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    confidence REAL NOT NULL,
    quality_score REAL,
    
    -- Reference to full output (stored separately)
    output_path TEXT
);

-- Table: eval_baselines
CREATE TABLE IF NOT EXISTS eval_baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metrics_json TEXT NOT NULL,
    golden_set_hash TEXT NOT NULL
);

-- Table: eval_alerts
CREATE TABLE IF NOT EXISTS eval_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    baseline_value REAL,
    current_value REAL,
    delta REAL,
    threshold REAL,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    acknowledged BOOLEAN DEFAULT 0
);
"""


class EvalDatabase:
    """Database operations for eval infrastructure."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database with schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(EVAL_SCHEMA)
            conn.commit()

    def _row_to_dict(self, cursor: sqlite3.Cursor, row: tuple) -> dict:
        """Convert row to dict using cursor description."""
        return {desc[0]: val for desc, val in zip(cursor.description, row)}

    def insert_eval_run(
        self,
        run_id: str,
        document_id: str,
        agent_type: str,
        schema_valid: bool,
        field_scores: dict[str, float],
        confidence: float,
        judge_scores: dict[str, float] | None = None,
        judge_reasoning: str | None = None,
        latency_ms: int = 0,
        model_used: str = "",
        prompt_version: str = "",
    ) -> None:
        """Insert an eval run result."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_eval_runs (
                    run_id, document_id, agent_type, schema_valid,
                    thesis_similarity, claims_similarity, trades_similarity,
                    talking_points_similarity, confidence_similarity, confidence,
                    judge_thesis_clarity, judge_claim_grounding,
                    judge_trading_actionability, judge_talking_point_quality,
                    judge_coherence, judge_reasoning,
                    latency_ms, model_used, prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    document_id,
                    agent_type,
                    schema_valid,
                    field_scores.get("thesis", 0),
                    field_scores.get("key_claims_claim", 0),
                    field_scores.get("trading_opportunities_thesis", 0),
                    field_scores.get("talking_points_text", 0),
                    field_scores.get("confidence", 0),
                    confidence,
                    judge_scores.get("thesis_clarity") if judge_scores else None,
                    judge_scores.get("claim_grounding") if judge_scores else None,
                    judge_scores.get("trading_actionability") if judge_scores else None,
                    judge_scores.get("talking_point_quality") if judge_scores else None,
                    judge_scores.get("coherence") if judge_scores else None,
                    judge_reasoning,
                    latency_ms,
                    model_used,
                    prompt_version,
                ),
            )
            conn.commit()

    def save_baseline(
        self,
        baseline_name: str,
        metrics: dict[str, float],
        golden_set_hash: str,
    ) -> None:
        """Save evaluation baseline."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_baselines (
                    baseline_name, metrics_json, golden_set_hash
                ) VALUES (?, ?, ?)
            """,
                (baseline_name, json.dumps(metrics), golden_set_hash),
            )
            conn.commit()

    def load_baseline(self, baseline_name: str) -> dict[str, float] | None:
        """Load evaluation baseline by name."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT metrics_json FROM eval_baselines WHERE baseline_name = ?",
                (baseline_name,),
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    def list_baselines(self) -> list[dict]:
        """List all baselines."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT baseline_name, created_at, golden_set_hash
                FROM eval_baselines
                ORDER BY created_at DESC
            """)
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def insert_training_capture(
        self,
        capture_id: str,
        document_id: str,
        agent_type: str,
        confidence: float,
        quality_score: float | None = None,
        output_path: str | None = None,
    ) -> None:
        """Insert a training capture."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO training_captures (
                    capture_id, document_id, agent_type, confidence, quality_score, output_path
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    capture_id,
                    document_id,
                    agent_type,
                    confidence,
                    quality_score,
                    output_path,
                ),
            )
            conn.commit()

    def get_training_captures(
        self,
        min_confidence: float = 0.0,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """Get training captures filtered by criteria."""
        query = "SELECT * FROM training_captures WHERE confidence >= ?"
        params = [min_confidence]

        if start_date:
            query += " AND captured_at >= ?"
            params.append(start_date)

        if end_date:
            query += " AND captured_at <= ?"
            params.append(end_date)

        query += " ORDER BY confidence DESC"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def insert_alert(
        self,
        alert_type: str,
        metric_name: str,
        baseline_value: float,
        current_value: float,
        delta: float,
        threshold: float,
    ) -> None:
        """Insert an alert."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO eval_alerts (
                    alert_type, metric_name, baseline_value, current_value, delta, threshold
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    alert_type,
                    metric_name,
                    baseline_value,
                    current_value,
                    delta,
                    threshold,
                ),
            )
            conn.commit()

    def get_unacknowledged_alerts(self) -> list[dict]:
        """Get unacknowledged alerts."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM eval_alerts
                WHERE acknowledged = 0
                ORDER BY triggered_at DESC
            """)
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]

    def acknowledge_alert(self, alert_id: int) -> None:
        """Acknowledge an alert."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE eval_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
            conn.commit()


def compute_golden_set_hash(golden_path: Path) -> str:
    """Compute hash of golden set for baseline tracking."""
    import hashlib

    annotations_path = golden_path / "annotations.jsonl"
    if not annotations_path.exists():
        return ""

    content = annotations_path.read_text()
    return hashlib.sha256(content.encode()).hexdigest()[:16]
