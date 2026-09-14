# Analysis Planning Round Closeout Plan

Last updated: 2026-03-29 America/New_York

## Goal

Close the March 26 to March 29 planning round for the proposed analysis layer and leave one clear execution handoff.

This document does not introduce new architecture.

It consolidates:

- which planning outputs are now source of truth
- which items are actual blockers before coding
- which open choices can be deferred into implementation
- the recommended order for the next execution phase

## Planning round outcome

The planning round is functionally complete.

The repo now has a coherent spec set for:

- analysis-layer scope and phase model
- chunk taxonomy
- assertion taxonomy
- world-model resolution and temporal updates
- persistence model
- migration draft
- operational run model
- bootstrap repo layout
- evaluation and retrieval posture
- upstream validation checklist

The upstream validation dependency has now been executed and documented in:

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)

## Source-of-truth documents

Use these documents as the active implementation references.

### Execution gate

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)
- [2026-03-27-upstream-integration-contract-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-upstream-integration-contract-spec.md)

### Service shape and operations

- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)

### Core semantic model

- [2026-03-26-analysis-chunk-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-chunk-taxonomy-spec.md)
- [2026-03-27-assertion-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-assertion-taxonomy-spec.md)
- [2026-03-27-world-model-resolution-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-world-model-resolution-spec.md)

### Storage and downstream use

- [2026-03-27-analysis-persistence-schema-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-persistence-schema-spec.md)
- [2026-03-27-analysis-schema-migration-draft.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-schema-migration-draft.md)
- [2026-03-27-evaluation-and-retrieval-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-evaluation-and-retrieval-plan.md)

## What is done

These planning questions now have working answers:

- the analysis layer owns chunking, assertion extraction, world-model maintenance, and provenance
- `state.db` is for change detection and job discovery, not for content hydration
- the parsed database is the authoritative content source
- the atomic processing unit is one hydrated parsed document row within a batch run
- chunk, evidence, assertion, node, and edge are separated into explicit layers
- lifecycle and authority are modeled separately
- world-model updates preserve contradiction and time rather than deleting prior meaning
- analysis-owned storage is expected to live in Postgres by default
- the first implementation should be a simple Python worker with a CLI entrypoint

## Resolved blockers

The previous blocker was upstream validation against real parser systems.

That blocker is now resolved at the planning level.

The material findings were:

- `state.db` is keyed by `file_id`, not `research_id`
- `updated_at` is the current usable watermark
- parsed content joins through `parsed_data.metadata.document_id`
- normalized theme and excerpt tables are live and populated

## Remaining execution prerequisites

Implementation should use the validated contract from the results spec.

No additional planning work is required before bootstrap coding.

## Non-blocking design choices

These decisions can be deferred to implementation or early migration work:

- whether intermediate document tables ever need a temporary SQLite mode for dev-only workflows
- how much parser metadata to mirror into `analysis_documents`
- whether `metadata_json` stays flexible in v1
- whether `open_question` later deserves a dedicated table family

The planning round does not need to resolve these now.

## Recommended execution order

1. scaffold the analysis repo from the bootstrap spec
2. translate the migration draft into concrete SQL
3. implement the Phase 1 ingestion loop and run-state tracking
4. implement deterministic chunking and evidence construction
5. implement assertion extraction, resolution, and idempotent graph updates

## Handoff guidance for the next agent

The next agent should not restart architecture design.

It should begin with bootstrap implementation using the validated upstream contract and results spec.

When in doubt:

- prefer the March 27 to March 29 spec set over the March 26 umbrella plan
- treat the migration draft as the SQL handoff, not the logical schema spec
- treat evaluation and retrieval as a consumer-facing guardrail, not a reason to expand v1 scope

## Documents now serving historical context

These remain useful background documents but should not be treated as the main execution entrypoint:

- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)
- [2026-03-22-theme-link-enrichment-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-22-theme-link-enrichment-spec.md)
- [2026-03-22-theme-normalization-migration-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-22-theme-normalization-migration-plan.md)

## Acceptance criteria

This planning round is closed when:

- a new agent can find the execution entrypoint in one document
- the remaining blocker is clearly upstream validation rather than more internal design
- the implementation order is explicit
- older umbrella plans no longer look like the active source of truth

## Related documents

- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)
- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-27-analysis-schema-migration-draft.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-schema-migration-draft.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)

## Status

`READY_FOR_BOOTSTRAP_EXECUTION`
