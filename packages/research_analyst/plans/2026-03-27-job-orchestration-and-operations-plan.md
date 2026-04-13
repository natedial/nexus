# Job Orchestration And Operations Plan

Last updated: 2026-03-27 America/New_York

## Goal

Define how the analysis layer runs operationally.

This spec covers:

- cron triggering
- reading parser `state.db`
- selecting work
- batching and claiming
- reruns and reprocessing
- backfills
- failure handling
- minimal observability requirements

## Operational model

The analysis layer should start as a cron-driven batch worker.

Recommended posture:

- simple scheduled execution first
- one worker process first
- clear run-state visibility first
- no queue system until operational load justifies it

## Trigger source

`state.db` is the change-detection source, not the content source.

Use it to answer:

- which parser jobs succeeded
- which `research_id` values are new or changed
- which documents are safe to fetch from the parsed database

Do not use it as the authoritative store for:

- themes
- excerpts
- raw content
- metadata beyond job-state selection fields

## Recommended run loop

1. cron launches the worker
2. worker creates one `analysis_runs` record
3. worker polls `state.db` for newly successful parser outputs since the last watermark
4. worker filters for analysis-eligible items
5. worker batches selected `research_id`s
6. worker fetches normalized content from parsed DB
7. worker processes each document atomically
8. worker records per-document results in `analysis_run_items`
9. worker advances the selection watermark only after successful run finalization

## Selection rules

Select a document when one of these is true:

- parser status is successful and no successful analysis run exists
- parser status is successful and `document_hash` differs from the last analyzed hash
- analysis version changed
- prior analysis status is `error`
- document was explicitly requested in a manual backfill or reprocess job

Do not select when:

- parser row is incomplete
- normalized content is missing or inconsistent
- a matching successful analysis record already exists for the same hash and version

## Watermark strategy

Track both:

- last seen parser event timestamp
- last successfully finalized parser event timestamp

Reason:

- prevents losing items when a run crashes after selection but before final commit

## Claiming and concurrency

V1 assumption:

- single worker is acceptable

Even so, persist claim status in case a second worker is introduced later.

Recommended per-item states:

- `queued`
- `claimed`
- `processing`
- `success`
- `error`
- `skipped_not_ready`
- `skipped_duplicate`

If later concurrency is needed:

- use row-level claiming in analysis-owned tables
- or use advisory locks keyed by `research_id`

## Batch sizing

Recommended defaults:

- cron every 5 to 15 minutes for near-real-time operation
- batch size 25 to 100 documents depending on parsed DB latency
- process documents sequentially at first

Reason:

- document analysis will likely vary in cost due to chunk count and graph updates
- sequential per-document atomicity is simpler and safer first

## Document-level atomicity

Each `research_id` should be the atomic unit for intermediate document analysis.

Within a document transaction:

- replace `analysis_chunks` for the current document hash
- replace `analysis_evidence_units` for the current document hash
- replace `analysis_assertions` for the current document hash
- update graph records with idempotent provenance joins
- record run-item success or error

If a document fails:

- do not leave partially replaced intermediate records for that hash
- do not double-count node/edge evidence
- record the failure and continue with the batch unless failure is systemic

## Manual operations

The worker should support these CLI modes:

- `run`
  - normal cron-triggered execution

- `backfill --date-from --date-to`
  - replay a date window

- `backfill --source`
  - replay a specific publisher/source

- `reprocess --research-id`
  - rerun one document

- `reprocess --document-hash`
  - rerun one exact version

- `reconcile`
  - detect mismatch between parser-success rows and analysis-owned records

## Recommended run statuses

Run-level:

- `running`
- `success`
- `partial_success`
- `error`

Document-level:

- `queued`
- `processing`
- `success`
- `skipped_not_ready`
- `skipped_no_signal`
- `skipped_duplicate`
- `error`

## Error taxonomy

Use a small controlled error taxonomy.

Recommended values:

- `state_db_unavailable`
- `parsed_db_unavailable`
- `document_not_found`
- `document_not_ready`
- `hydration_error`
- `chunking_error`
- `assertion_extraction_error`
- `graph_update_error`
- `write_error`
- `unknown_error`

Persist both:

- `error_type`
- `error_text`

## Retry strategy

Recommended posture:

- automatic retry only for transient infrastructure failures
- no blind infinite retry for semantic or data-shape failures

Suggested behavior:

- infrastructure errors: retry with bounded exponential backoff
- data-shape errors: mark `error`, require later reprocess after upstream fix
- graph update conflicts: retry once, then error

## Versioning strategy

Track at least:

- `analysis_version`
- `chunker_version`
- `assertion_extractor_version`
- `resolver_version`

Rationale:

- not every code change should force a full historical rebuild
- targeted reprocessing becomes possible when versions are isolated

## Readiness checks before analysis

Before processing a document, verify:

- parser status is success
- parsed document row exists
- normalized themes are present when expected
- `document_hash` is non-null
- source metadata is coherent enough for local storage

Optional:

- raw content is present if a fallback chunking path depends on it

## Minimal observability

Each run should emit:

- start time
- end time
- document count
- success/error/skip counts
- average processing time per document
- chunk count distribution
- assertion count distribution
- graph upsert counts
- top error categories

At document level, persist:

- chunk count
- assertion count
- node count touched
- edge count touched
- whether open questions were created

## Safety rules

- never advance the watermark before run finalization
- never double-count evidence from the same assertion on rerun
- never require graph updates to succeed before intermediate analysis is stored if salvageable partial staging is useful
- never silently drop parser-success documents because of one batch failure

## Suggested module responsibilities

- `scheduler.py`
  - cron entrypoint and run orchestration

- `state_reader.py`
  - reads parser `state.db`

- `selector.py`
  - decides which documents to process

- `parser_client.py`
  - fetches normalized content from parsed DB

- `writer.py`
  - persists run state and intermediate records

- `reconcile.py`
  - audits drift between parser and analysis layer

## Acceptance criteria

This operating model is sufficient when:

- cron runs can detect and process new parser-success documents safely
- failed documents do not block the whole corpus forever
- reruns are idempotent
- manual backfills are possible
- operators can explain why a given document was or was not processed

## Related documents

- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)
- [2026-03-27-analysis-persistence-schema-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-persistence-schema-spec.md)

## Status

`READY_FOR_AGENT_IMPLEMENTATION`
