# Nexus Centralized Batch Operations Plan

**Date:** 2026-10-20

**Status:** Implemented; producer canaries and monitor activation pending

**Scope:** Nexus-wide scheduled and batch operations
**Primary owner:** `packages/research_pipeline_ops`

## Objective

Create one operational control plane for Nexus batch jobs so that a scheduled
agent can answer four questions reliably:

1. Which jobs should have run?
2. What happened during each run?
3. Which failures or stalls still need attention?
4. Which recovery actions are safe to perform automatically?

The control plane records operational metadata only. Package-owned ledgers
remain authoritative for domain state, delivery idempotency, capture identity,
and document processing state.

## Success criteria

- Every enabled scheduled Nexus job records a terminal run state.
- Missing, failed, degraded, and stalled jobs appear in one structured query.
- Repeated observations of the same problem produce one incident with an
  occurrence count rather than repeated notifications.
- A monitor can claim an incident with a lease, preventing two agents from
  attempting the same repair concurrently.
- Only explicitly allowlisted, idempotent jobs may be retried automatically.
- Every remediation attempt is auditable and linked to an incident.
- PostgreSQL unavailability does not break the domain job; events are spooled
  locally and replayed idempotently after recovery.
- No secrets or research/email content are written to the operations schema.

## What already exists

| Existing component | Current state | Plan |
| --- | --- | --- |
| `migrations/003_pipeline_ops_schema.sql` | Applied locally; defines runs, stage events, projections, and basic views | Retained and extended additively |
| Parser instrumentation | Emits poll runs and per-document stage events through the in-repo client | Canary before enabling the catalog job |
| Analyst instrumentation | Emits hourly parent runs and per-document stage events | Canary before enabling the catalog job |
| Canonical dispatcher instrumentation | Morning Attention generation/handoff emits one summarized run | Keep external delivery outside this status |
| Relay SQLite ledger and alerts | Remains authoritative while email, archive, and enqueue publish summarized outcomes | Keep automatic retry disabled |
| Gleaner SQLite store and source locks | Remains authoritative while Notion and reMarkable sweeps publish summarized outcomes | Canary before enabling both catalog jobs |
| PostgreSQL container | Hosts the applied control-plane schema and disabled-by-default job catalog | Enable jobs individually after canaries |

`packages/research_pipeline_ops` now provides the shared client, durable SQLite
spool, monitor, incident lifecycle, safe retry policy, CLI, and agent skill.
Migration 005 is applied locally. All catalog jobs remain disabled until their
manual and scheduled canaries have been reviewed.

## Scope challenge

The minimum complete solution is not a dashboard or a new daemon. It is:

1. one additive database migration;
2. one small shared Python package;
3. thin adapters at each real scheduled entry point; and
4. one scheduled agent routine using the package CLI.

Implementation must be split into package-sized pull requests. A single
cross-repository-style change would touch too many entry points to canary or
revert safely.

## Architecture

```text
                  package-owned domain work
        +------------------------------------------+
        | parser | analyst | relay | gleaner | MA |
        +----+-------+--------+--------+--------+--+
             |       operational event envelope |
             v                                  v
      +------------------------------------------------+
      | research_pipeline_ops client                   |
      | validate -> redact -> PostgreSQL transaction   |
      |                    \-> SQLite spool on outage   |
      +-------------------------+----------------------+
                                |
                                v
      +------------------------------------------------+
      | PostgreSQL pipeline_ops                        |
      | jobs | runs | stage_events | current state     |
      | incidents | remediation_attempts               |
      +-------------------------+----------------------+
                                |
                   nexus-ops check/claim/retry/resolve
                                |
                                v
      +------------------------------------------------+
      | scheduled Codex agent                          |
      | quiet if healthy -> claim -> diagnose ->       |
      | allowlisted retry -> verify -> record/notify   |
      +------------------------------------------------+
```

### Dependency boundary

`research_pipeline_ops` owns transport, validation, status semantics,
scheduling checks, incident lifecycle, and remediation audit records. It does
not import any producer package.

Producer packages own mapping their domain results into the shared run model.
They install the shared package alongside themselves with an editable sibling
install during local deployment. Docker images explicitly copy and install the
shared package. The existing `sys.path` discovery hacks are removed after each
consumer has moved to the installed package.

## Data model

### Existing tables retained

- `pipeline_ops.runs`
- `pipeline_ops.stage_events`
- `pipeline_ops.documents`
- `pipeline_ops.document_stage_state`
- `pipeline_ops.run_stage_state`

### Changes to `runs`

Add:

- `job_key TEXT NULL REFERENCES pipeline_ops.jobs(job_key)`
- `heartbeat_at TIMESTAMPTZ NULL`
- `exit_code INTEGER NULL`

Standardize run status to:

```text
running -> succeeded
        -> degraded
        -> failed
        -> skipped
```

`degraded` means the run completed but one or more non-fatal work items failed.
`skipped` means the invocation intentionally did no work, such as an overlap
lock. An empty successful poll remains `succeeded`, not `skipped`.

### `jobs`

The job catalog gives stable identity and monitoring policy to scheduled work.

Required fields:

- `job_key` — stable dotted identifier, such as `gleaner.notion`
- `repo_name`, `run_type`
- `enabled`
- `schedule_type` — `interval`, `daily`, `weekdays`, or `external`
- interval or local calendar schedule fields
- IANA timezone for calendar schedules
- grace and stall thresholds
- `retry_policy` — `never` or `kickstart_once`
- `launchd_label` when the retry policy uses launchd
- `playbook_key`
- timestamps

Commands are never stored in this table. This prevents a database write from
becoming arbitrary code execution.

### `incidents`

One row represents one unresolved operational condition. Required fields:

- stable `incident_key`
- `job_key`, optional latest `run_key`
- `kind` — `failed`, `degraded`, `stalled`, `overdue`, `spool_backlog`, or
  `control_plane_unavailable`
- severity
- failure fingerprint
- first/last seen timestamps and occurrence count
- `open`, `claimed`, `resolved`, or `suppressed` state
- lease owner and expiry
- resolution summary and timestamps

Failure fingerprints group repeated occurrences of the same sanitized error
kind. A later successful run automatically resolves active failure, degraded,
stalled, and overdue incidents for that job.

### `remediation_attempts`

Append-only audit rows record:

- incident and job keys
- actor
- action key
- `started`, `succeeded`, `failed`, or `declined` status
- start/completion timestamps
- sanitized result metadata and error text

### Indexes and retention

Add indexes for:

- latest run by `(job_key, started_at DESC)`
- open incidents by `(status, severity, last_seen_at)`
- remediation attempts by `(incident_key, started_at DESC)`

Keep stage events for 90 days. Keep aggregate runs, incidents, and remediation
history for one year initially; retention is configurable through explicit
garbage-collection functions.

## Shared client

The package exposes one primary class, `PipelineOpsClient`, with this API:

```python
client = PipelineOpsClient.from_env(
    emitted_by="research_gleaner",
    default_spool_db_path=".../pipeline_ops_spool.db",
)

run_key = client.start_run(job_key="gleaner.notion", trigger_source="launchd")
client.heartbeat(run_key, stats={"documents_seen": 12})
client.emit_stage_event(...)
client.finish_run(run_key, status="succeeded", stats={...}, exit_code=0)
client.flush()
```

`track_stage(...)` remains as a context manager for the existing parser,
analyst, and dispatcher call sites.

### Failure semantics

- Invalid statuses or unsafe payload types fail before the domain operation;
  these are programming errors.
- PostgreSQL connection and transaction failures are transport failures. The
  validated envelope is written to SQLite and the domain operation continues.
- Replay is ordered and idempotent through unique operation/event keys.
- A spool row is deleted only after the corresponding PostgreSQL transaction
  commits.
- Errors are sanitized and truncated before either destination is written.
- A bounded spool size produces a loud local error and a `spool_backlog`
  condition when the database becomes available again.

### Environment

- `PIPELINE_OPS_DATABASE_URL`, falling back to `NEXUS_DATABASE_URL`
- `PIPELINE_OPS_MODE=required|best_effort|off`
- `PIPELINE_OPS_ERROR_TEXT_MAX_CHARS`, with a conservative default
- package-owned spool paths passed by each producer

Production scheduled jobs use `best_effort`: missing/invalid configuration is
reported, while transient database failure spools locally. Tests cover
`required` mode for deployment validation. `off` exists for explicit local
development only.

## Job catalog and remediation policy

Initial catalog:

| Job key | Expected cadence | Stall threshold | Automatic retry | Reason |
| --- | --- | --- | --- | --- |
| `relay.email` | Every 5 minutes | 6 minutes | No | Already retries frequently; SMTP has a duplicate-delivery crash window |
| `relay.archive` | Every 8 hours | 70 minutes | No initially | External Drive writes require canary evidence before automatic replay |
| `gleaner.notion` | Daily 04:00 ET | 30 minutes | Once | Capture identity and revision state make reruns idempotent |
| `gleaner.remarkable` | Daily 04:10 ET | 45 minutes | Once | Revision deduplication makes reruns idempotent |
| `parser.poll` | Configured interval | Interval plus processing allowance | Once | Parser state deduplicates completed documents and retries partial work |
| `analyst.hourly` | Hourly | 90 minutes | Once | Run/item state supports bounded reprocessing |
| `dispatcher.morning_attention_handoff` | Weekdays 06:25 ET | 30 minutes | No | Nexus can attest to generation/handoff, but not the external Proey delivery |

An automatic retry means a single `launchctl kickstart -k` using an allowlisted
label assembled as an argument vector with `shell=False`. It does not mean:

- resetting relay circuit breakers;
- forcing an archive upload;
- resending email or Morning Attention output;
- changing credentials or configuration;
- mutating package domain ledgers; or
- executing a command read from PostgreSQL.

## Package adoption

### Gleaner

Instrument only the mutating `notion` and `remarkable` commands. `query` is not
a batch job.

Run summaries contain source kind, documents inspected, captures observed,
new captures, reconciled removals where available, duration, and output file
identity. They never contain highlight text, page content, source URLs, or
Notion tokens.

Overlap lock exits record `skipped`; source/API errors record `failed`.

### Relay

Instrument `run`, `archive`, and `archive-enqueue` as distinct job keys; only
the first two are initially expected on a schedule.

Relay result counters map to:

- `succeeded` when the exit code is zero and no operational degradation exists;
- `degraded` when work completes with item-level temporary/permanent failures;
- `failed` on process-level operational failure; and
- `skipped` on overlap lock or explicitly disabled archive work.

The relay's SQLite ledger remains authoritative for send/archive idempotency.
Ops payloads contain counts and error classes only—never addresses, subjects,
message IDs, attachment names, or bodies.

### Parser

Keep existing run and per-document stages. Add periodic run heartbeats during
large polls and standardize terminal status. Parser domain state continues to
control document retries.

### Analyst

Keep existing batch and document events. The hourly runner records a parent
`analyst.hourly` run covering batch draining and forecast synchronization;
individual analysis batches remain linked child runs or stages. Heartbeat after
each drained batch.

### Dispatcher

Do not treat legacy `src/main.py` as the only production path. Instrument
`src/claim_notes/run_morning_attention.py`, which is invoked by the current
fallback schedule and produces the documented canonical handoff. Its terminal
success means **handoff produced**, not externally delivered.

Do not enable a separate `dispatcher.morning_attention_delivery` job until the
Proey-owned routine exposes a trustworthy delivery receipt or emits its own
terminal event. This avoids presenting an inferred delivery as observed fact.

An empty but valid claims window is `succeeded` with zero output, not skipped or
failed. Delivery failures are terminal failures and are never automatically
retried by the control plane.

## Monitor and agent contract

The package provides a `nexus-ops` CLI:

```text
nexus-ops check --json
nexus-ops incidents --status open --json
nexus-ops claim --actor <agent-id> --limit 5 --lease-minutes 20 --json
nexus-ops retry --incident <key> --dry-run
nexus-ops retry --incident <key>
nexus-ops resolve --incident <key> --summary <text>
nexus-ops decline --incident <key> --reason <text>
```

`check` performs four operations in one transaction where possible:

1. calculate missing, stalled, failed, and degraded conditions;
2. upsert/deduplicate incidents;
3. resolve incidents superseded by a later healthy run; and
4. return the current attention queue.

The scheduled agent routine runs every 15 minutes:

```text
check
  |
  +-- healthy ---------------------------------> stay quiet
  |
  +-- attention needed -> claim incident
                            |
                            +-- retry_policy=kickstart_once
                            |      -> dry-run validation
                            |      -> retry
                            |      -> wait for terminal run
                            |      -> recheck and record outcome
                            |
                            +-- retry_policy=never
                                   -> collect playbook context
                                   -> notify with exact user action
```

The automation must stay quiet while state is unchanged. It notifies only on a
new incident, failed remediation, recovery, or required human action.

## Concurrency and state transitions

```text
             check observes problem
                      |
                      v
                    open
                 /    |    \
        lease acquired |     newer healthy run
               v       |             |
            claimed    |             v
          /    |    \   |          resolved
   retry ok retry fail decline
       |       |        |
       v       v        v
   resolved   open   suppressed
              ^
              |
          lease expires
```

- Claims use row locks and `FOR UPDATE SKIP LOCKED`.
- Expired claims return to `open` on the next check.
- One automatic attempt is allowed per incident occurrence and cooldown window.
- A new failure after a recorded recovery opens a new occurrence.

## Privacy and security requirements

- Central payloads use per-job allowlists, not arbitrary dictionaries copied
  from domain objects.
- Generic sanitization removes credential-bearing URLs, common token patterns,
  and control characters, then truncates text.
- Relay adapters perform their existing private-address redaction before the
  generic sanitizer.
- PostgreSQL commands and launchd labels are never accepted from incident error
  text or payload JSON.
- Repair execution uses argument arrays and `shell=False`.
- The monitor database role should receive only the operations-schema access it
  needs; producer roles may append/update runs but may not edit remediation
  policy.

## Failure modes

| Code path | Production failure | Handling | Test |
| --- | --- | --- | --- |
| Direct event write | PostgreSQL unavailable | Spool validated envelope and continue | Unit + integration |
| Spool replay | Crash after DB commit, before spool delete | Unique operation key makes replay idempotent | Integration |
| Run process | Process killed without terminal update | Heartbeat age creates stalled incident | Integration |
| Calendar check | DST or weekend boundary | `zoneinfo` schedule calculation with explicit weekdays/timezone | Table-driven unit |
| Incident check | Two agents run together | Row lock, skip-locked claim, expiring lease | Concurrent integration |
| Deduplication | Same failure repeats every run | Fingerprint upsert increments occurrence count | Unit + integration |
| Recovery | Later run succeeds | Resolve only incidents older than the healthy run | Integration |
| Retry | Database payload contains malicious command text | Retry uses compiled allowlist and stored launchd label only | Security unit |
| Retry | LaunchAgent exits unsuccessfully | Attempt marked failed; incident returns open after cooldown | Unit |
| Relay instrumentation | Error includes private content | Adapter allowlist plus redaction/truncation | Unit |
| Gleaner instrumentation | Capture object accidentally passed as stats | Payload schema rejects non-allowlisted fields | Unit |
| Control plane | Ops package missing in deployment | Deployment doctor fails before enabling schedule | Smoke test |

No planned failure path is both silent and without error handling.

## Test plan

```text
producer result
  |
  +-- success --------------------------> run=succeeded
  +-- partial/nonfatal -----------------> run=degraded
  +-- process error --------------------> run=failed
  +-- overlap/disabled -----------------> run=skipped
  +-- process killed -------------------> run=running -> stalled incident
  |
  +-- PostgreSQL available -------------> committed event + projection
  +-- PostgreSQL unavailable -----------> SQLite spool
                                           |
                                           +-- replay success -> committed once
                                           +-- replay failure -> retained

monitor check
  |
  +-- latest healthy and on time --------> no incident
  +-- never ran / overdue ---------------> overdue incident
  +-- heartbeat expired -----------------> stalled incident
  +-- terminal unhealthy ----------------> failed/degraded incident
  +-- later healthy run -----------------> resolve prior incident

claimed incident
  |
  +-- policy never ----------------------> decline + notify
  +-- policy retry once -----------------> launchd kickstart
       +-- healthy terminal run ---------> resolve
       +-- failure/timeout --------------> attempt failed + notify
```

### Foundation tests

- Validation for every status and identifier.
- Start, heartbeat, stage, and finish transactions.
- Context manager success and exception behavior.
- Error sanitization, truncation, and payload allowlists.
- SQLite spool ordering, retry, crash recovery, size bound, and idempotency.
- Migration application against a clean database and the current schema.
- Run/stage projection correctness.
- Schedule calculations across DST, weekends, grace windows, disabled jobs,
  and jobs that have never run.
- Incident creation, deduplication, recovery, suppression, leases, and cooldowns.
- Retry allowlist and command construction security.

### Adapter tests

Each producer gets table-driven tests for every terminal outcome and verifies
that sensitive/domain content is absent from the emitted payload.

### End-to-end acceptance test

1. Insert or run a synthetic healthy job and confirm `check` is empty.
2. Run a synthetic failure and confirm one incident.
3. Repeat the same failure and confirm the occurrence count increments without
   creating another incident.
4. Claim it from two concurrent clients and confirm only one succeeds.
5. Record an allowlisted retry and a later successful run.
6. Confirm the incident resolves and the remediation audit remains.
7. Stop PostgreSQL, emit a run into the spool, restart PostgreSQL, flush, and
   confirm the run appears exactly once.

## Performance

Expected event volume is small. The checker reads one latest run per enabled
job and open incidents only. Spool replay uses bounded batches and one database
transaction per batch. JSON payloads remain small and indexed fields stay in
typed columns.

No metrics stack, queue broker, background API, or cache is warranted at this
scale.

## Delivery sequence

### File-level change map

The exact filenames may shift slightly during implementation, but the ownership
boundary should remain:

| Area | Files to add or change |
| --- | --- |
| Shared schema | `migrations/005_pipeline_ops_control_plane.sql`, `migrations/README.md` |
| Shared package | `packages/research_pipeline_ops/pyproject.toml`, `src/research_pipeline_ops/{__init__,client,monitor,cli}.py`, focused tests, package README |
| Gleaner adapter | `packages/research_gleaner/pyproject.toml`, `src/research_gleaner/cli.py`, CLI tests, README/install scripts |
| Relay adapter | `packages/research-relay/pyproject.toml`, `src/research_relay/cli.py`, CLI tests, README/install scripts |
| Parser adapter | `packages/research_parser/pyproject.toml`, `src/pipeline.py`, pipeline tests, deployment files |
| Analyst adapter | `packages/research_analyst/pyproject.toml`, `pipelines/run_batch.py`, `scripts/hourly_runner.sh`, tests, deployment files |
| Dispatcher adapter | `packages/research_dispatcher/src/claim_notes/run_morning_attention.py`, its tests, operations docs |
| Agent routine | Codex automation configuration after the notification-only canary is ready |

Spooling stays inside `client.py` unless that file becomes difficult to test in
isolation; avoid creating a separate abstraction merely to mirror the storage
mechanism. Monitoring, incident lifecycle, and remediation policy stay together
in `monitor.py` because they form one operational state machine.

### PR 1 — Foundation

Owned by `packages/research_pipeline_ops` plus root migration/docs.

- Add package metadata and shared client.
- Add the control-plane migration.
- Add CLI, incident checker, safe retry executor, and tests.
- Seed the job catalog disabled by default.
- Add a deployment doctor and migration smoke test.

**Gate:** all foundation tests pass; synthetic end-to-end flow passes; no
producer has changed behavior yet.

### PR 2 — Gleaner adoption

- Install shared package in gleaner setup.
- Instrument Notion and reMarkable sweeps.
- Enable both catalog jobs after one manual observed run each.
- Canary automatic retry with dry-run first, then live once-only retry.

**Gate:** two consecutive scheduled successes for each job and verified
overdue detection from a deliberately disabled test schedule.

### PR 3 — Relay adoption

- Instrument relay, archive, and archive-enqueue outcomes.
- Keep all relay automatic retry disabled.
- Reconcile ops status with existing relay alerts without duplicating repeated
  notifications.

**Gate:** event payload privacy tests pass; live canary produces counts matching
the relay ledger; no addresses or message metadata appear in PostgreSQL.

### PR 4 — Parser and analyst adoption

- Replace the missing external client dependency with the in-repo package.
- Standardize statuses and add heartbeats.
- Instrument the analyst hourly parent run.
- Remove obsolete import-path discovery after deployment packaging is updated.

**Gate:** existing package suites pass; document/run projection parity holds;
stalled synthetic jobs are detected and safe retries remain idempotent.

### PR 5 — Dispatcher adoption

- Instrument canonical Morning Attention generation/handoff without claiming
  external delivery.
- Keep delivery retries manual.
- Retain legacy dispatcher instrumentation only while that entry point remains
  supported.

**Gate:** empty windows are healthy, handoff-generation errors open incidents,
and the recorded status never implies external delivery.

### PR 6 — Agent automation activation

- Create the 15-minute scheduled check.
- Start notification-only for one week.
- Enable allowlisted retries for gleaner.
- Enable parser/analyst retries only after their canary evidence is reviewed.

**Gate:** unchanged healthy state is silent; new/recovered incidents notify
once; every action has a remediation audit row.

## Rollback

- Disable a job in `pipeline_ops.jobs` to stop monitoring it without changing
  the producer.
- Set `PIPELINE_OPS_MODE=off` to stop emission during package rollback.
- Keep migrations additive; do not drop package domain data or old logs.
- Disable automatic retry independently of observation by setting
  `retry_policy=never`.
- The domain jobs continue to operate if the control plane is unavailable.

## NOT in scope

- A web dashboard or custom UI; the CLI and agent summary are sufficient.
- Replacing package-owned SQLite/domain ledgers.
- Arbitrary shell-command remediation.
- Automatic credential rotation, configuration edits, circuit-breaker resets,
  forced delivery, or destructive replay.
- Full distributed tracing or an external observability stack.
- Logging research text, highlights, email metadata, generated reports, or
  prompts.
- Per-document automatic repair across every pipeline stage; initial repair is
  at the scheduled-job boundary.
- Moving all schedules into a new orchestrator.

## Open implementation checks

These are verification tasks, not unresolved architecture choices:

- Confirm the production parser interval and deployment mechanism before
  enabling `parser.poll` in the catalog.
- Confirm whether Proey exposes a trustworthy delivery receipt before adding a
  separate delivery-observation job; handoff monitoring does not depend on it.
- Decide the exact PostgreSQL role grants during PR 1 based on current local
  deployment users.

## Definition of done

The work is complete when all seven initial scheduled jobs have produced
observed terminal runs, the agent has completed a notification-only canary, at
least one synthetic retry/recovery has been audited end to end, privacy queries
show no domain content in ops payloads, and operational documentation contains
the install, doctor, check, recovery, and rollback commands.
