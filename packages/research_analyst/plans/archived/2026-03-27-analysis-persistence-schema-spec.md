# Analysis Persistence And Schema Spec

Last updated: 2026-03-27 America/New_York

## Goal

Define the analysis-owned persistence model for this repo.

This spec covers:

- which records this service should own
- how those records relate to parser-owned identifiers
- which fields should be persisted for provenance and world-model maintenance
- how lifecycle, authority, and temporal updates should be stored

This is a logical schema spec, not a final SQL migration.

## Persistence principles

- keep parser-owned extraction tables separate from analysis-owned tables
- store provenance as a first-class concern
- preserve enough history to reinterpret the model later
- prefer append-and-update semantics over destructive rewriting of meaning
- allow reprocessing without duplicating semantic records uncontrollably
- do not require raw PDF text copies unless needed for fallback inspection

## Ownership boundary

Parser-owned source of truth:

- `state.db` for trigger detection
- parsed database tables for normalized document content

Analysis-owned source of truth:

- chunking outputs
- evidence units
- extracted assertions
- world nodes and edges
- provenance joins
- run state and operational metadata

## Recommended table groups

### Operational tables

- `analysis_runs`
- `analysis_run_items`
- `analysis_backfill_jobs`

### Document analysis tables

- `analysis_documents`
- `analysis_chunks`
- `analysis_evidence_units`
- `analysis_assertions`

### World-model tables

- `world_nodes`
- `world_edges`
- `world_node_evidence`
- `world_edge_evidence`
- `world_node_aliases`
- `world_questions`
- `world_edge_history`

### Optional review and QA tables

- `analysis_reviews`
- `analysis_review_items`

## Recommended core tables

## `analysis_documents`

Purpose:

- mirror the parser document identity inside the analysis layer
- cache stable metadata needed for local processing and debugging

Key fields:

- `id`
- `research_id`
- `document_hash`
- `source`
- `source_date`
- `title`
- `publisher`
- `region`
- `asset_focus`
- `ingested_at`
- `last_analyzed_at`
- `latest_successful_run_id`

Constraints:

- unique on `research_id`
- index on `(source_date, source)`
- index on `document_hash`

## `analysis_runs`

Purpose:

- track each cron/manual execution

Key fields:

- `id`
- `run_type`
- `status`
- `trigger_source`
- `started_at`
- `completed_at`
- `document_count`
- `success_count`
- `error_count`
- `skipped_count`
- `notes`

Recommended `run_type` values:

- `cron`
- `manual_backfill`
- `manual_reprocess`
- `debug`

Recommended `status` values:

- `running`
- `success`
- `partial_success`
- `error`

## `analysis_run_items`

Purpose:

- record per-document status within a run

Key fields:

- `id`
- `run_id`
- `research_id`
- `document_hash`
- `status`
- `selected_reason`
- `error_text`
- `chunk_count`
- `assertion_count`
- `node_upsert_count`
- `edge_upsert_count`
- `started_at`
- `completed_at`

Recommended `status` values:

- `queued`
- `processing`
- `success`
- `skipped_not_ready`
- `skipped_no_signal`
- `error`

## `analysis_chunks`

Purpose:

- persist the topical analysis boundaries for each document

Key fields:

- `id`
- `research_id`
- `document_hash`
- `chunk_order`
- `chunk_type`
- `section_name`
- `title`
- `text`
- `topic_tags_json`
- `entity_tags_json`
- `horizon_tag`
- `page_start`
- `page_end`
- `paragraph_start`
- `paragraph_end`
- `created_run_id`

Constraints:

- unique on `(research_id, document_hash, chunk_order)`
- index on `chunk_type`

## `analysis_evidence_units`

Purpose:

- persist small support spans used by assertions and graph records

Key fields:

- `id`
- `research_id`
- `chunk_id`
- `evidence_order`
- `evidence_type`
- `text`
- `normalized_text`
- `page_ref`
- `source_ref_json`
- `parser_theme_id`
- `created_run_id`

Recommended `evidence_type` values:

- `excerpt`
- `context_span`
- `theme_label`
- `theme_context`
- `raw_text_fallback`
- `structured_fact`

## `analysis_assertions`

Purpose:

- persist semantic claims extracted from chunks

Key fields:

- `id`
- `research_id`
- `chunk_id`
- `assertion_order`
- `assertion_type`
- `text`
- `normalized_text`
- `summary_text`
- `polarity`
- `confidence_label`
- `extraction_confidence`
- `time_horizon`
- `time_anchor`
- `condition_text`
- `qualifier_text`
- `status`
- `authority_band`
- `authority_score`
- `support_count`
- `contradiction_count`
- `source_diversity`
- `last_supported_at`
- `last_contested_at`
- `created_run_id`
- `superseded_by_assertion_id`

Supporting join table:

- `analysis_assertion_evidence`
  - `assertion_id`
  - `evidence_unit_id`

## `world_nodes`

Purpose:

- represent evolving cross-document concepts and entities

Key fields:

- `id`
- `node_type`
- `canonical_label`
- `summary_text`
- `status`
- `authority_band`
- `authority_score`
- `support_count`
- `contradiction_count`
- `source_diversity`
- `first_seen_at`
- `last_seen_at`
- `last_supported_at`
- `last_contested_at`
- `regime_count`
- `is_active`
- `metadata_json`

Recommended `node_type` values:

- `concept`
- `event`
- `forecast`
- `realized_data_point`
- `market_impact`
- `entity`
- `instrument`
- `open_question`

## `world_node_aliases`

Purpose:

- preserve alternative names and soft canonicalization evidence

Key fields:

- `id`
- `world_node_id`
- `alias_text`
- `alias_type`
- `first_seen_research_id`
- `last_seen_research_id`
- `count_seen`

Recommended `alias_type` values:

- `source_phrase`
- `normalized_phrase`
- `ticker`
- `instrument_name`
- `question_variant`

## `world_edges`

Purpose:

- represent relationships between world nodes

Key fields:

- `id`
- `from_node_id`
- `to_node_id`
- `edge_type`
- `directionality`
- `status`
- `authority_band`
- `authority_score`
- `support_count`
- `contradiction_count`
- `source_diversity`
- `first_seen_at`
- `last_seen_at`
- `last_supported_at`
- `last_contested_at`
- `regime_count`
- `is_active`
- `explanation`
- `metadata_json`

Recommended `edge_type` values:

- `same_idea_as`
- `related_to`
- `supports`
- `contradicts`
- `qualifies`
- `drives`
- `implies`
- `reacts_to`
- `forecasts`
- `realized_as`
- `impacts`
- `raises_question`

Constraints:

- unique on `(from_node_id, to_node_id, edge_type)`
- enforce canonical ordering for symmetric edges

## `world_node_evidence`

Purpose:

- map nodes back to assertion and evidence support

Key fields:

- `id`
- `world_node_id`
- `assertion_id`
- `evidence_unit_id`
- `research_id`
- `support_role`
- `weight`
- `created_at`

Recommended `support_role` values:

- `direct_support`
- `alias_support`
- `question_support`
- `contradictory_support`

## `world_edge_evidence`

Purpose:

- map edges back to assertion and evidence support

Key fields:

- `id`
- `world_edge_id`
- `assertion_id`
- `evidence_unit_id`
- `research_id`
- `support_role`
- `weight`
- `created_at`

Recommended `support_role` values:

- `direct_support`
- `reinforcement`
- `contradiction`
- `qualification`

## `world_edge_history`

Purpose:

- keep temporal snapshots of meaningful edge-state changes

Key fields:

- `id`
- `world_edge_id`
- `recorded_at`
- `status`
- `authority_band`
- `authority_score`
- `support_count`
- `contradiction_count`
- `change_reason`
- `trigger_research_id`

## `world_questions`

Purpose:

- optionally separate unresolved questions from other nodes if dedicated handling becomes useful

Recommended approach:

- start with `open_question` as a `world_node` type
- add this table only if workflow needs separate resolution state and review logic

## Reprocessing strategy

Recommended posture:

- document-derived chunks, evidence, and raw assertions may be replaced per document hash
- world nodes and edges should be updated, not blindly deleted
- provenance joins should always retain the triggering `research_id`

This means:

- destructive replace is acceptable for intermediate per-document analysis records
- append/update semantics are preferred for world-model records

## Suggested document-level idempotency rule

For a given `(research_id, document_hash, analysis_version)`:

- rerunning chunking and assertion extraction should produce the same intermediate records
- graph updates may increase counters only once for the same provenance pair

Therefore:

- provenance joins should carry uniqueness constraints preventing double-counting of the same assertion-evidence contribution

## Lifecycle storage guidance

Persist lifecycle fields directly on:

- `analysis_assertions`
- `world_nodes`
- `world_edges`

Do not calculate them only on the fly.

Reason:

- they are operationally important
- downstream retrieval should be able to query by them efficiently

## Recommended indexes

- `analysis_documents(research_id)`
- `analysis_chunks(research_id, chunk_order)`
- `analysis_assertions(research_id, chunk_id)`
- `analysis_assertions(assertion_type, status, authority_band)`
- `world_nodes(node_type, status, authority_band)`
- `world_nodes(last_seen_at)`
- `world_edges(edge_type, status, authority_band)`
- `world_edges(from_node_id, to_node_id)`
- `world_edge_evidence(world_edge_id, research_id)`
- `world_node_evidence(world_node_id, research_id)`

## Open design choices

- whether intermediate document analysis tables live in Postgres or a local SQLite store
- whether `analysis_documents` mirrors only selected parser metadata or all useful metadata
- whether `metadata_json` should remain flexible or be normalized further later
- when to promote `open_question` into its own dedicated table family

## Acceptance criteria

This schema direction is ready when:

- the service can rerun safely without double-counting graph support
- every node and edge can be explained from provenance tables
- document-level intermediate outputs can be replaced without corrupting long-lived world-model state
- downstream retrieval can query by `status`, `authority_band`, and recency

## Related documents

- [2026-03-27-assertion-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-assertion-taxonomy-spec.md)
- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)

## Status

`READY_FOR_SCHEMA_DESIGN`
