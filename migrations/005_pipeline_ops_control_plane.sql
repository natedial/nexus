-- Nexus centralized batch-operations control plane.
-- Additive extension to 003_pipeline_ops_schema.sql.

CREATE SCHEMA IF NOT EXISTS pipeline_ops;

CREATE TABLE IF NOT EXISTS pipeline_ops.jobs (
    job_key TEXT PRIMARY KEY,
    repo_name TEXT NOT NULL,
    run_type TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    enabled_at TIMESTAMPTZ NULL,
    schedule_type TEXT NOT NULL,
    schedule_interval_seconds INTEGER NULL,
    schedule_local_time TIME NULL,
    schedule_weekdays SMALLINT[] NULL,
    schedule_timezone TEXT NULL,
    grace_seconds INTEGER NOT NULL DEFAULT 900,
    stall_seconds INTEGER NOT NULL DEFAULT 1800,
    retry_policy TEXT NOT NULL DEFAULT 'never',
    launchd_label TEXT NULL,
    playbook_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_pipeline_ops_job_schedule_type
        CHECK (schedule_type IN ('interval', 'daily', 'weekdays', 'external')),
    CONSTRAINT chk_pipeline_ops_job_retry_policy
        CHECK (retry_policy IN ('never', 'kickstart_once')),
    CONSTRAINT chk_pipeline_ops_job_intervals
        CHECK (
            grace_seconds >= 0
            AND stall_seconds > 0
            AND (schedule_interval_seconds IS NULL OR schedule_interval_seconds > 0)
        ),
    CONSTRAINT chk_pipeline_ops_job_schedule_fields
        CHECK (
            (schedule_type = 'interval' AND schedule_interval_seconds IS NOT NULL)
            OR (schedule_type IN ('daily', 'weekdays')
                AND schedule_local_time IS NOT NULL
                AND schedule_timezone IS NOT NULL)
            OR schedule_type = 'external'
        ),
    CONSTRAINT chk_pipeline_ops_job_retry_target
        CHECK (
            retry_policy = 'never'
            OR (retry_policy = 'kickstart_once' AND launchd_label IS NOT NULL)
        )
);

ALTER TABLE pipeline_ops.runs
    ADD COLUMN IF NOT EXISTS job_key TEXT NULL,
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS exit_code INTEGER NULL;

UPDATE pipeline_ops.runs
SET status = CASE status
    WHEN 'completed' THEN 'succeeded'
    WHEN 'error' THEN 'failed'
    ELSE status
END
WHERE status IN ('completed', 'error');

UPDATE pipeline_ops.runs
SET heartbeat_at = COALESCE(completed_at, updated_at, started_at)
WHERE heartbeat_at IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_pipeline_ops_runs_job'
          AND conrelid = 'pipeline_ops.runs'::regclass
    ) THEN
        ALTER TABLE pipeline_ops.runs
            ADD CONSTRAINT fk_pipeline_ops_runs_job
            FOREIGN KEY (job_key) REFERENCES pipeline_ops.jobs(job_key);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_pipeline_ops_run_status'
          AND conrelid = 'pipeline_ops.runs'::regclass
    ) THEN
        ALTER TABLE pipeline_ops.runs
            ADD CONSTRAINT chk_pipeline_ops_run_status
            CHECK (status IN ('running', 'succeeded', 'degraded', 'failed', 'skipped'))
            NOT VALID;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_runs_job_started
    ON pipeline_ops.runs(job_key, started_at DESC)
    WHERE job_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_runs_running_heartbeat
    ON pipeline_ops.runs(heartbeat_at)
    WHERE status = 'running';

CREATE OR REPLACE FUNCTION pipeline_ops.touch_job_configuration()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    IF TG_OP = 'INSERT' THEN
        IF NEW.enabled AND NEW.enabled_at IS NULL THEN
            NEW.enabled_at = now();
        END IF;
    ELSIF NEW.enabled AND NOT OLD.enabled THEN
        NEW.enabled_at = now();
    ELSIF NOT NEW.enabled AND OLD.enabled THEN
        NEW.enabled_at = NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_pipeline_ops_touch_job_configuration
    ON pipeline_ops.jobs;
CREATE TRIGGER trg_pipeline_ops_touch_job_configuration
BEFORE INSERT OR UPDATE ON pipeline_ops.jobs
FOR EACH ROW
EXECUTE FUNCTION pipeline_ops.touch_job_configuration();

CREATE TABLE IF NOT EXISTS pipeline_ops.ingested_operations (
    operation_key TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    emitted_by TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_ingested_operations_time
    ON pipeline_ops.ingested_operations USING brin(ingested_at);

CREATE TABLE IF NOT EXISTS pipeline_ops.incidents (
    incident_key TEXT PRIMARY KEY,
    job_key TEXT NOT NULL REFERENCES pipeline_ops.jobs(job_key),
    latest_run_key TEXT NULL REFERENCES pipeline_ops.runs(run_key),
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    lease_owner TEXT NULL,
    lease_expires_at TIMESTAMPTZ NULL,
    resolved_at TIMESTAMPTZ NULL,
    resolution_summary TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_pipeline_ops_incident_kind
        CHECK (kind IN (
            'failed', 'degraded', 'stalled', 'overdue',
            'spool_backlog', 'control_plane_unavailable'
        )),
    CONSTRAINT chk_pipeline_ops_incident_severity
        CHECK (severity IN ('warning', 'error', 'critical')),
    CONSTRAINT chk_pipeline_ops_incident_status
        CHECK (status IN ('open', 'claimed', 'resolved', 'suppressed')),
    CONSTRAINT chk_pipeline_ops_incident_occurrences
        CHECK (occurrence_count > 0),
    CONSTRAINT chk_pipeline_ops_incident_lease
        CHECK (
            (status = 'claimed' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
            OR status <> 'claimed'
        )
);

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_incidents_attention
    ON pipeline_ops.incidents(status, severity, last_seen_at DESC)
    WHERE status IN ('open', 'claimed');

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_incidents_job_status
    ON pipeline_ops.incidents(job_key, status);

CREATE TABLE IF NOT EXISTS pipeline_ops.remediation_attempts (
    id BIGSERIAL PRIMARY KEY,
    incident_key TEXT NOT NULL REFERENCES pipeline_ops.incidents(incident_key) ON DELETE CASCADE,
    job_key TEXT NOT NULL REFERENCES pipeline_ops.jobs(job_key),
    incident_occurrence INTEGER NOT NULL,
    actor TEXT NOT NULL,
    action_key TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NULL,
    CONSTRAINT chk_pipeline_ops_remediation_status
        CHECK (status IN ('started', 'succeeded', 'failed', 'declined')),
    CONSTRAINT chk_pipeline_ops_remediation_occurrence
        CHECK (incident_occurrence > 0)
);

CREATE INDEX IF NOT EXISTS ix_pipeline_ops_remediation_incident_time
    ON pipeline_ops.remediation_attempts(incident_key, started_at DESC);

CREATE OR REPLACE VIEW pipeline_ops.v_agent_attention AS
SELECT
    i.incident_key,
    i.job_key,
    i.latest_run_key,
    i.kind,
    i.severity,
    i.summary,
    i.status,
    i.occurrence_count,
    i.first_seen_at,
    i.last_seen_at,
    i.lease_owner,
    i.lease_expires_at,
    j.retry_policy,
    j.playbook_key,
    j.launchd_label
FROM pipeline_ops.incidents i
JOIN pipeline_ops.jobs j USING (job_key)
WHERE i.status IN ('open', 'claimed')
ORDER BY
    CASE i.severity WHEN 'critical' THEN 0 WHEN 'error' THEN 1 ELSE 2 END,
    i.last_seen_at DESC;

CREATE OR REPLACE FUNCTION pipeline_ops.gc_old_control_plane_data(
    operation_retention INTERVAL DEFAULT interval '90 days',
    history_retention INTERVAL DEFAULT interval '1 year'
)
RETURNS TABLE(operations_deleted INTEGER, incidents_deleted INTEGER)
LANGUAGE plpgsql
AS $$
DECLARE
    op_count INTEGER;
    incident_count INTEGER;
BEGIN
    DELETE FROM pipeline_ops.ingested_operations
    WHERE ingested_at < now() - operation_retention;
    GET DIAGNOSTICS op_count = ROW_COUNT;

    DELETE FROM pipeline_ops.incidents
    WHERE status IN ('resolved', 'suppressed')
      AND resolved_at < now() - history_retention;
    GET DIAGNOSTICS incident_count = ROW_COUNT;

    RETURN QUERY SELECT op_count, incident_count;
END;
$$;

INSERT INTO pipeline_ops.jobs (
    job_key, repo_name, run_type, enabled, schedule_type,
    schedule_interval_seconds, schedule_local_time, schedule_weekdays,
    schedule_timezone, grace_seconds, stall_seconds, retry_policy,
    launchd_label, playbook_key
) VALUES
    ('relay.email', 'research_relay', 'email', FALSE, 'interval',
        300, NULL, NULL, NULL, 120, 360, 'never',
        'com.researchrelay.email', 'relay.email'),
    ('relay.archive', 'research_relay', 'archive', FALSE, 'interval',
        28800, NULL, NULL, NULL, 1800, 4200, 'never',
        'com.researchrelay.archive', 'relay.archive'),
    ('relay.archive_enqueue', 'research_relay', 'archive_enqueue', FALSE, 'external',
        NULL, NULL, NULL, NULL, 900, 1800, 'never',
        NULL, 'relay.archive_enqueue'),
    ('gleaner.notion', 'research_gleaner', 'notion', FALSE, 'daily',
        NULL, '04:00', NULL, 'America/New_York', 3600, 1800, 'kickstart_once',
        'com.researchgleaner.notion-sweep', 'gleaner.notion'),
    ('gleaner.remarkable', 'research_gleaner', 'remarkable', FALSE, 'daily',
        NULL, '04:10', NULL, 'America/New_York', 3600, 2700, 'kickstart_once',
        'com.researchgleaner.remarkable-sweep', 'gleaner.remarkable'),
    ('parser.poll', 'research_parser', 'poll_cycle', FALSE, 'interval',
        300, NULL, NULL, NULL, 300, 1800, 'never',
        NULL, 'parser.poll'),
    ('analyst.hourly', 'research_analyst', 'hourly', FALSE, 'interval',
        3600, NULL, NULL, NULL, 1800, 5400, 'never',
        NULL, 'analyst.hourly'),
    ('dispatcher.morning_attention_handoff', 'research_dispatcher',
        'morning_attention_handoff', FALSE, 'weekdays', NULL, '06:25',
        ARRAY[1,2,3,4,5]::smallint[], 'America/New_York', 1800, 1800,
        'never', NULL, 'dispatcher.morning_attention_handoff')
ON CONFLICT (job_key) DO NOTHING;
