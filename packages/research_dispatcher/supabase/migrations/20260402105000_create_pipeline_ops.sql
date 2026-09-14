CREATE SCHEMA IF NOT EXISTS pipeline_ops;

CREATE TABLE IF NOT EXISTS pipeline_ops.documents (
    document_key TEXT PRIMARY KEY,
    file_id TEXT NULL,
    research_id BIGINT NULL,
    document_hash TEXT NULL,
    document_name TEXT NULL,
    source TEXT NULL,
    source_date DATE NULL,
    publisher TEXT NULL,
    region TEXT NULL,
    asset_focus TEXT NULL,
    parser_updated_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_ops.runs (
    run_key TEXT PRIMARY KEY,
    repo_name TEXT NOT NULL,
    stage_family TEXT NOT NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    host TEXT NULL,
    worker_id TEXT NULL,
    trigger_source TEXT NULL,
    batch_key TEXT NULL,
    analysis_version TEXT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pipeline_ops.stage_events (
    id BIGSERIAL PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    occurred_at TIMESTAMPTZ NOT NULL,
    repo_name TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    document_key TEXT NULL,
    run_key TEXT NULL,
    file_id TEXT NULL,
    research_id BIGINT NULL,
    document_hash TEXT NULL,
    attempt INTEGER NULL,
    duration_ms BIGINT NULL,
    queue_lag_ms BIGINT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_type TEXT NULL,
    error_text TEXT NULL,
    emitted_by TEXT NULL,
    CONSTRAINT chk_stage_event_status
        CHECK (status IN ('queued', 'started', 'heartbeat', 'succeeded', 'failed', 'skipped', 'retrying', 'stalled'))
);

CREATE TABLE IF NOT EXISTS pipeline_ops.document_stage_state (
    document_key TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    current_status TEXT NOT NULL,
    last_event_at TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ NULL,
    last_failure_at TIMESTAMPTZ NULL,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    latest_run_key TEXT NULL,
    latest_duration_ms BIGINT NULL,
    latest_queue_lag_ms BIGINT NULL,
    error_type TEXT NULL,
    error_text TEXT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (document_key, stage_name)
);

CREATE TABLE IF NOT EXISTS pipeline_ops.run_stage_state (
    run_key TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    repo_name TEXT NOT NULL,
    current_status TEXT NOT NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    processed_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms BIGINT NULL,
    p95_duration_ms BIGINT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_key, stage_name)
);

CREATE INDEX IF NOT EXISTS ix_stage_events_document_stage
    ON pipeline_ops.stage_events(document_key, stage_name);

CREATE INDEX IF NOT EXISTS ix_stage_events_stage_status_time
    ON pipeline_ops.stage_events(stage_name, status, occurred_at);

CREATE INDEX IF NOT EXISTS ix_stage_events_run_key
    ON pipeline_ops.stage_events(run_key);

CREATE INDEX IF NOT EXISTS ix_stage_events_occurred_brin
    ON pipeline_ops.stage_events USING brin(occurred_at);

CREATE INDEX IF NOT EXISTS ix_stage_events_failed_time
    ON pipeline_ops.stage_events(stage_name, occurred_at DESC)
    WHERE status = 'failed';

CREATE OR REPLACE VIEW pipeline_ops.v_failures_recent AS
SELECT
    occurred_at,
    repo_name,
    stage_name,
    document_key,
    run_key,
    error_type,
    error_text,
    payload_json
FROM pipeline_ops.stage_events
WHERE status = 'failed'
ORDER BY occurred_at DESC;

CREATE OR REPLACE VIEW pipeline_ops.v_stage_backlog AS
SELECT
    stage_name,
    count(*) FILTER (WHERE current_status = 'queued') AS queued_count,
    count(*) FILTER (WHERE current_status IN ('started', 'heartbeat', 'retrying')) AS running_count,
    count(*) FILTER (
        WHERE current_status = 'failed'
          AND last_failure_at >= now() - interval '24 hours'
    ) AS failed_24h,
    count(*) FILTER (
        WHERE current_status IN ('started', 'heartbeat', 'retrying')
          AND last_event_at < now() - interval '30 minutes'
    ) AS stalled_count,
    min(last_event_at) FILTER (
        WHERE current_status IN ('started', 'heartbeat', 'retrying')
    ) AS oldest_inflight_at,
    round(avg(latest_duration_ms))::bigint AS avg_duration_ms,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY latest_duration_ms) AS p95_duration_ms
FROM pipeline_ops.document_stage_state
GROUP BY stage_name;

CREATE OR REPLACE VIEW pipeline_ops.v_document_progress AS
WITH pivoted AS (
    SELECT
        d.document_key,
        d.file_id,
        d.research_id,
        d.document_hash,
        d.document_name,
        d.source,
        d.source_date,
        max(CASE WHEN s.stage_name = 'parser.complete' THEN s.current_status END) AS parser_status,
        max(CASE WHEN s.stage_name = 'parser.complete' THEN s.last_event_at END) AS parser_completed_at,
        max(CASE WHEN s.stage_name = 'analyst.complete' THEN s.current_status END) AS analyst_status,
        max(CASE WHEN s.stage_name = 'analyst.complete' THEN s.last_event_at END) AS analyst_completed_at,
        max(CASE WHEN s.stage_name = 'store.complete' THEN s.current_status END) AS store_status,
        max(CASE WHEN s.stage_name = 'store.complete' THEN s.last_event_at END) AS store_completed_at,
        max(CASE WHEN s.stage_name = 'dispatcher.complete' THEN s.current_status END) AS dispatcher_status,
        max(CASE WHEN s.stage_name = 'dispatcher.complete' THEN s.last_event_at END) AS dispatcher_completed_at,
        max(s.last_event_at) AS current_stage_updated_at
    FROM pipeline_ops.documents d
    LEFT JOIN pipeline_ops.document_stage_state s
        ON s.document_key = d.document_key
    GROUP BY
        d.document_key,
        d.file_id,
        d.research_id,
        d.document_hash,
        d.document_name,
        d.source,
        d.source_date
)
SELECT
    *,
    CASE
        WHEN coalesce(parser_status, 'missing') <> 'succeeded' THEN 'parser.complete'
        WHEN coalesce(analyst_status, 'missing') <> 'succeeded' THEN 'analyst.complete'
        WHEN coalesce(store_status, 'missing') <> 'succeeded' THEN 'store.complete'
        WHEN coalesce(dispatcher_status, 'missing') <> 'succeeded' THEN 'dispatcher.complete'
        ELSE NULL
    END AS current_blocking_stage
FROM pivoted;

CREATE OR REPLACE FUNCTION pipeline_ops.gc_old_stage_events(
    retention_window INTERVAL DEFAULT interval '90 days'
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM pipeline_ops.stage_events
    WHERE occurred_at < now() - retention_window;

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;
