# Analysis Upstream Validation Plan

Last updated: 2026-03-29 America/New_York

## Goal

Turn the upstream contract in this repo into a verified implementation input.

This plan exists to remove the remaining ambiguity before a coding agent builds:

- `StateDbReader`
- `ParsedDbClient`
- readiness checks
- selection logic
- initial migrations

## Why this is the next step

The March 27 planning batch already marks the architecture, operations model, bootstrap shape, and migration draft as ready for implementation.

The main unresolved dependency is upstream reality:

- actual `state.db` schema and semantics
- actual parsed DB access path and table names
- actual document/theme/excerpt field availability
- actual readiness signals for a document version

Without that validation, the first coding pass would still be inventing adapters.

## Scope

This plan covers validation of:

- parser `state.db`
- parsed database access method
- parsed document/theme/excerpt tables
- document version semantics
- sample corpus quality for chunking and evidence extraction

This plan does not cover:

- implementing the analysis worker
- writing production SQL migrations
- designing new parser-owned fields

## Validation questions to answer

The validation pass should produce explicit answers for these questions.

### `state.db`

- Which table or tables represent parser job outcomes?
- Is `research_id` present, stable, and directly usable by the analysis layer?
- Is there a trustworthy success timestamp such as `completed_at`?
- What exact `status` values exist, and which one means content is ready?
- Does one parser rerun overwrite prior rows or append new rows?
- Is `document_hash` present in `state.db`, or only in the parsed database?
- Which field should be used as the selection watermark?

### Parsed database

- Is access direct Postgres, Supabase, or an application wrapper?
- Which table holds authoritative document rows?
- Which table holds normalized themes?
- Which table holds excerpts or equivalent supporting text spans?
- Are raw content, raw spans, or page references available anywhere?
- Which joins are required to hydrate one `research_id` completely?

### Data quality and semantics

- Does `theme_count` exist, and does it match actual theme rows?
- Are theme excerpts ordered?
- Do excerpts include page numbers, paragraph offsets, or other span metadata?
- Are there documents with normalized themes but unusable excerpts?
- How often are optional metadata fields such as `title`, `publisher`, `region`, and `asset_focus` absent?
- When a document changes, does it keep the same `research_id` and get a new `document_hash`, or is a new document row created?

## Workstreams

## Workstream 1: inspect `state.db`

Goal:

- verify the operational trigger contract

Tasks:

- inspect the schema for tables relevant to parser run status
- list columns, types, indexes, and obvious uniqueness constraints
- inspect a small sample of success and failure rows
- identify the exact success-state semantics
- determine whether the analysis watermark should use `completed_at`, another timestamp, or a row id

Record in the follow-up notes:

- table names
- relevant columns
- example success row shape
- example failure row shape
- confirmed selection watermark field
- confirmed join key into parsed content

## Workstream 2: inspect parsed DB structure

Goal:

- verify the content hydration contract

Tasks:

- locate the authoritative document table
- locate normalized theme and excerpt tables
- inspect key columns, nullability, and joins
- verify whether `document_hash` lives on the document row
- verify whether `theme_count` is stored or derived
- verify whether raw text or raw spans are available

Record in the follow-up notes:

- table names
- join path for `research_id -> document -> themes -> excerpts`
- required fields that exist as-is
- required fields that need adaptation or fallback handling
- optional fields that are present often enough to rely on

## Workstream 3: sample corpus review

Goal:

- confirm that real documents are analyzable with the planned chunking/evidence pipeline

Target sample:

- 20 to 30 representative notes
- mix of sources
- mix of short and long notes
- mix of high-theme-count and low-theme-count notes
- at least a few recent reruns or corrected documents if available

Review checklist per sample:

- document metadata completeness
- normalized theme quality
- excerpt usefulness for chunking
- ordering quality
- need for raw content fallback
- obvious failure modes for assertion extraction

Summarize:

- patterns that are safe for v1 assumptions
- patterns that require guardrails
- patterns that should block coding until upstream clarification

## Expected outputs

The validation agent should produce one follow-up document in this repo with:

- verified upstream table names
- verified field mappings
- example row shapes
- confirmed readiness rules
- mismatches against the March 27 contract
- recommended adapter behavior for each mismatch

Recommended filename:

- `plans/2026-03-29-analysis-upstream-validation-results-spec.md`

Execution result:

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)

If major mismatches are found, also update:

- [2026-03-27-upstream-integration-contract-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-upstream-integration-contract-spec.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)

## Implementation gates

Bootstrap implementation should proceed only after these are known:

- exact `state.db` success table and watermark field
- exact parsed DB access path
- exact join path for document hydration
- confirmed source of `document_hash`
- confirmed meaning of a stable document version
- confirmed minimum viable fields for readiness checks

Migration work can proceed in parallel only where it does not depend on upstream naming.

## Suggested validation commands

These are examples, not fixed commands.

- inspect SQLite schema for `state.db`
- query a handful of recent success rows
- describe parsed DB tables relevant to documents, themes, and excerpts
- query a few hydrated documents end to end by `research_id`
- compare stored `theme_count` against actual child row counts

The follow-up doc should preserve the exact commands or SQL used so the inspection is reproducible.

## Risks to surface explicitly

- parser success rows that do not guarantee parsed DB readiness
- missing or unstable `research_id`
- `document_hash` only available after an extra join
- excerpt tables without ordering or span metadata
- documents whose normalized themes are too sparse for chunking without raw text
- parser reruns that rewrite rows in a way that breaks simple watermark logic

## Acceptance criteria

This validation plan is sufficient when:

- another agent can execute it without inventing the inspection scope
- the results will directly unblock adapter implementation
- the exit criteria clearly separate safe assumptions from unsafe ones

## Related documents

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)
- [2026-03-27-upstream-integration-contract-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-upstream-integration-contract-spec.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)
- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)

## Status

`SUPERSEDED_BY_VALIDATION_RESULTS_SPEC`
