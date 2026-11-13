-- Allow the `stale_running` incident kind emitted by research_pipeline_ops
-- (monitor.stale_running_condition). 005 created the CHECK constraint before
-- stale-running detection existed, so incident upserts of that kind were
-- rejected. Idempotent: apply.sh re-runs every migration file.

BEGIN;

ALTER TABLE pipeline_ops.incidents
    DROP CONSTRAINT IF EXISTS chk_pipeline_ops_incident_kind;

ALTER TABLE pipeline_ops.incidents
    ADD CONSTRAINT chk_pipeline_ops_incident_kind
        CHECK (kind IN (
            'failed', 'degraded', 'stalled', 'overdue',
            'spool_backlog', 'control_plane_unavailable', 'stale_running'
        ));

COMMIT;
