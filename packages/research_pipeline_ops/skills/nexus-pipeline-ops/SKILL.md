---
name: nexus-pipeline-ops
description: Check and triage centralized Nexus batch-job health with nexus-ops. Use when an agent needs to inspect failures, stalled schedules, or stale running orphans, claim incidents, preview or apply reap-stale cleanup when authorized, perform an explicitly authorized allowlisted retry, or record a verified resolution. Do not use for schema deployment, job configuration, or arbitrary process execution.
---

# Nexus Pipeline Ops

Operate through the supported CLI rather than querying `pipeline_ops` tables or
calling `launchctl` directly. Run commands from the Nexus repository root with
the root environment loaded:

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops COMMAND
```

Never print or pass the database URL on the command line. The CLI reads
`PIPELINE_OPS_DATABASE_URL` or `NEXUS_DATABASE_URL` from `.env`.

## Check health

Verify configuration and schema availability first:

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops doctor
```

If `schema_exists`, `jobs_exists`, or `incidents_exists` is false, stop and
report that migrations are required. Do not apply migrations or enable jobs
unless the user separately requests deployment work.

Refresh health and return the attention queue:

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops check --json
```

`check` evaluates enabled job schedules, materializes current incidents, closes
conditions that have recovered, and releases expired claims. It also opens
`stale_running` when any `running` row for an enabled job has
`coalesce(heartbeat_at, started_at)` older than
`max(stall_seconds, grace_seconds, 3600)` — including orphans behind a newer
successful run. Latest-run heartbeat failure still uses catalog `stall_seconds`
alone as kind `stalled`. If there are no items, report healthy state only when
the task asks for status; recurring monitors should remain quiet when nothing
changed.

Use `incidents --status open --json` when the task needs a read-only view without
refreshing health.

## Reap stale running rows

Crash orphans can leave hundreds of `running` rows after a producer dies. Preview
counts per job first (dry-run is the default; never print the database URL):

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops reap-stale --json
```

Apply only when the user explicitly authorizes cleanup. Optional `--job JOB_KEY`
limits the update. Matching rows become `failed` with
`error_text = 'reaped: no heartbeat'`. Rows still inside the per-job heartbeat
threshold are never updated.

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops reap-stale --apply --json
```

After apply, re-run `check --json`. Recovered `stale_running` incidents should
resolve automatically.

## Triage and remediate

Claim work before attempting resolution so multiple agents do not act on the
same incident:

```bash
uv run --env-file .env --project packages/research_pipeline_ops nexus-ops claim \
  --actor AGENT_ID --limit 5 --lease-minutes 20 --json
```

For each claimed item, inspect `job_key`, `kind`, `severity`, `summary`,
`retry_policy`, `playbook_key`, and `occurrence_count`.

- Always preview retry eligibility and the allowlisted action first:

  ```bash
  uv run --env-file .env --project packages/research_pipeline_ops nexus-ops retry \
    --incident INCIDENT_KEY --actor AGENT_ID --dry-run
  ```

- Perform a live retry only when the user or saved routine explicitly authorizes
  remediation and the dry run returns `status: dry_run`. The control plane
  permits only catalogued `kickstart_once` jobs and only one attempt per incident
  occurrence.
- A successful kickstart means the scheduler accepted the launch; it does not
  prove the job recovered. Re-run `check --json` after the producer has had time
  to report a new run. Let the monitor resolve recovered conditions.
- Use `resolve` only when independent evidence confirms recovery and include a
  concise factual summary. Use `decline` only when the user explicitly accepts
  or suppresses the condition.

Do not edit the database, change the job catalog, apply migrations, enable or
disable jobs, or run an unlisted repair action as part of incident triage.

## Reporting

Report the incident key, job, condition, action taken, and verification result.
Do not expose connection strings, environment values, raw credentials, or
unredacted producer payloads. If remediation is not authorized or the retry is
declined by policy, leave the incident claimed until its lease expires and state
the required next action.
