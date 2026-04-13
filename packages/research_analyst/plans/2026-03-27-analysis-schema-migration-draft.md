# Analysis Schema Migration Draft

Last updated: 2026-03-27 America/New_York

## Goal

Translate the analysis persistence model into a migration-oriented draft that another agent can turn into concrete SQL.

This document is intentionally closer to implementation than the logical schema spec, but it still leaves room for final SQL dialect adjustments after upstream inspection.

## Scope

This draft covers analysis-owned storage for:

- run and backfill tracking
- document-level intermediate analysis
- assertion persistence
- world-model nodes and edges
- provenance joins
- edge history

This draft does not attempt to mutate parser-owned tables.

## Storage recommendation

Recommended default:

- use Postgres for analysis-owned durable storage

Reason:

- graph/world-model records are long-lived
- downstream retrieval will want indexed query access
- lifecycle and authority updates are not a good fit for ad hoc local-only SQLite once this grows

Acceptable transitional exception:

- a local SQLite database may be used for early dev-only operational testing

## Naming posture

Use an `analysis_` prefix for intermediate/document records and `world_` prefix for durable world-model records.

This keeps ownership visible and avoids collision with parser-owned tables.

## Proposed migration phases

### Migration 001: operational and document analysis core

Create:

- `analysis_runs`
- `analysis_run_items`
- `analysis_documents`
- `analysis_chunks`
- `analysis_evidence_units`
- `analysis_assertions`
- `analysis_assertion_evidence`

### Migration 002: world-model core

Create:

- `world_nodes`
- `world_node_aliases`
- `world_edges`
- `world_node_evidence`
- `world_edge_evidence`
- `world_edge_history`

### Migration 003: optional operations and review helpers

Create:

- `analysis_backfill_jobs`
- `analysis_backfill_job_items`
- `analysis_reviews`
- `analysis_review_items`

## Proposed enums

If the stack prefers text check constraints instead of native enums, use text plus checks.

### `analysis_run_status`

- `running`
- `success`
- `partial_success`
- `error`

### `analysis_run_type`

- `cron`
- `manual_backfill`
- `manual_reprocess`
- `debug`

### `analysis_run_item_status`

- `queued`
- `claimed`
- `processing`
- `success`
- `skipped_not_ready`
- `skipped_no_signal`
- `skipped_duplicate`
- `error`

### `chunk_type`

- `thesis_summary`
- `macro_view`
- `market_view`
- `asset_view`
- `event_analysis`
- `data_interpretation`
- `forecast_block`
- `trade_rationale`
- `risk_scenario`
- `positioning_flow`
- `policy_view`
- `cross_asset_linkage`
- `methodology_context`
- `misc_context`

### `evidence_type`

- `excerpt`
- `context_span`
- `theme_label`
- `theme_context`
- `raw_text_fallback`
- `structured_fact`

### `assertion_type`

- `observation`
- `interpretation`
- `forecast`
- `causal_claim`
- `market_impact`
- `policy_claim`
- `trade_claim`
- `risk_condition`
- `comparative_view`
- `open_question`

### `lifecycle_status`

- `proposed`
- `supported`
- `reinforced`
- `contested`
- `stale`
- `invalidated`

### `authority_band`

- `seed`
- `emerging`
- `established`
- `core`
- `structural`

### `world_node_type`

- `concept`
- `event`
- `forecast`
- `realized_data_point`
- `market_impact`
- `entity`
- `instrument`
- `open_question`

### `world_edge_type`

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

### `edge_maturity`

- `trace`
- `path`
- `road`
- `highway`
- `structural`

## Draft tables

## `analysis_runs`

```sql
CREATE TABLE analysis_runs (
    id BIGSERIAL PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    assertion_extractor_version TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT NULL,
    CHECK (run_type IN ('cron', 'manual_backfill', 'manual_reprocess', 'debug')),
    CHECK (status IN ('running', 'success', 'partial_success', 'error'))
);
```

Indexes:

- `idx_analysis_runs_started_at` on `started_at`
- `idx_analysis_runs_status` on `status`

## `analysis_run_items`

```sql
CREATE TABLE analysis_run_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    research_id BIGINT NOT NULL,
    document_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    selected_reason TEXT NOT NULL,
    error_type TEXT NULL,
    error_text TEXT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    assertion_count INTEGER NOT NULL DEFAULT 0,
    node_upsert_count INTEGER NOT NULL DEFAULT 0,
    edge_upsert_count INTEGER NOT NULL DEFAULT 0,
    open_question_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    CHECK (
        status IN (
            'queued',
            'claimed',
            'processing',
            'success',
            'skipped_not_ready',
            'skipped_no_signal',
            'skipped_duplicate',
            'error'
        )
    )
);
```

Indexes:

- `idx_analysis_run_items_run_id` on `run_id`
- `idx_analysis_run_items_research_id` on `research_id`
- `idx_analysis_run_items_status` on `status`

Recommended uniqueness:

- unique on `(run_id, research_id)`

## `analysis_documents`

```sql
CREATE TABLE analysis_documents (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL UNIQUE,
    document_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    source_date DATE NULL,
    title TEXT NULL,
    publisher TEXT NULL,
    region TEXT NULL,
    asset_focus TEXT NULL,
    parser_completed_at TIMESTAMPTZ NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_analyzed_at TIMESTAMPTZ NULL,
    latest_successful_run_id BIGINT NULL REFERENCES analysis_runs(id) ON DELETE SET NULL
);
```

Indexes:

- `idx_analysis_documents_source_date` on `(source_date, source)`
- `idx_analysis_documents_document_hash` on `document_hash`

## `analysis_chunks`

```sql
CREATE TABLE analysis_chunks (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES analysis_documents(research_id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    chunk_order INTEGER NOT NULL,
    chunk_type TEXT NOT NULL,
    section_name TEXT NULL,
    title TEXT NULL,
    text TEXT NOT NULL,
    topic_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    entity_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    horizon_tag TEXT NULL,
    page_start INTEGER NULL,
    page_end INTEGER NULL,
    paragraph_start INTEGER NULL,
    paragraph_end INTEGER NULL,
    created_run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    CHECK (
        chunk_type IN (
            'thesis_summary',
            'macro_view',
            'market_view',
            'asset_view',
            'event_analysis',
            'data_interpretation',
            'forecast_block',
            'trade_rationale',
            'risk_scenario',
            'positioning_flow',
            'policy_view',
            'cross_asset_linkage',
            'methodology_context',
            'misc_context'
        )
    )
);
```

Constraints:

- unique on `(research_id, document_hash, chunk_order)`

Indexes:

- `idx_analysis_chunks_research_id` on `research_id`
- `idx_analysis_chunks_chunk_type` on `chunk_type`

## `analysis_evidence_units`

```sql
CREATE TABLE analysis_evidence_units (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES analysis_documents(research_id) ON DELETE CASCADE,
    chunk_id BIGINT NOT NULL REFERENCES analysis_chunks(id) ON DELETE CASCADE,
    evidence_order INTEGER NOT NULL,
    evidence_type TEXT NOT NULL,
    text TEXT NOT NULL,
    normalized_text TEXT NULL,
    page_ref TEXT NULL,
    source_ref_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    parser_theme_id BIGINT NULL,
    created_run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    CHECK (
        evidence_type IN (
            'excerpt',
            'context_span',
            'theme_label',
            'theme_context',
            'raw_text_fallback',
            'structured_fact'
        )
    )
);
```

Constraints:

- unique on `(chunk_id, evidence_order)`

Indexes:

- `idx_analysis_evidence_units_chunk_id` on `chunk_id`
- `idx_analysis_evidence_units_research_id` on `research_id`

## `analysis_assertions`

```sql
CREATE TABLE analysis_assertions (
    id BIGSERIAL PRIMARY KEY,
    research_id BIGINT NOT NULL REFERENCES analysis_documents(research_id) ON DELETE CASCADE,
    chunk_id BIGINT NOT NULL REFERENCES analysis_chunks(id) ON DELETE CASCADE,
    assertion_order INTEGER NOT NULL,
    assertion_type TEXT NOT NULL,
    text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    summary_text TEXT NULL,
    polarity TEXT NOT NULL DEFAULT 'not_applicable',
    confidence_label TEXT NOT NULL DEFAULT 'medium',
    extraction_confidence TEXT NOT NULL DEFAULT 'medium',
    time_horizon TEXT NOT NULL DEFAULT 'unknown',
    time_anchor DATE NULL,
    condition_text TEXT NULL,
    qualifier_text TEXT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    authority_band TEXT NOT NULL DEFAULT 'seed',
    authority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 1,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 1,
    last_supported_at TIMESTAMPTZ NULL,
    last_contested_at TIMESTAMPTZ NULL,
    created_run_id BIGINT NOT NULL REFERENCES analysis_runs(id) ON DELETE RESTRICT,
    superseded_by_assertion_id BIGINT NULL REFERENCES analysis_assertions(id) ON DELETE SET NULL,
    CHECK (
        assertion_type IN (
            'observation',
            'interpretation',
            'forecast',
            'causal_claim',
            'market_impact',
            'policy_claim',
            'trade_claim',
            'risk_condition',
            'comparative_view',
            'open_question'
        )
    ),
    CHECK (status IN ('proposed', 'supported', 'reinforced', 'contested', 'stale', 'invalidated')),
    CHECK (authority_band IN ('seed', 'emerging', 'established', 'core', 'structural')),
    CHECK (polarity IN ('positive', 'negative', 'neutral', 'mixed', 'not_applicable')),
    CHECK (confidence_label IN ('low', 'medium', 'high', 'explicit_high')),
    CHECK (extraction_confidence IN ('low', 'medium', 'high'))
);
```

Constraints:

- unique on `(chunk_id, assertion_order)`

Indexes:

- `idx_analysis_assertions_research_id` on `research_id`
- `idx_analysis_assertions_chunk_id` on `chunk_id`
- `idx_analysis_assertions_type_status` on `(assertion_type, status)`
- `idx_analysis_assertions_authority` on `authority_band`

## `analysis_assertion_evidence`

```sql
CREATE TABLE analysis_assertion_evidence (
    assertion_id BIGINT NOT NULL REFERENCES analysis_assertions(id) ON DELETE CASCADE,
    evidence_unit_id BIGINT NOT NULL REFERENCES analysis_evidence_units(id) ON DELETE CASCADE,
    PRIMARY KEY (assertion_id, evidence_unit_id)
);
```

## `world_nodes`

```sql
CREATE TABLE world_nodes (
    id BIGSERIAL PRIMARY KEY,
    node_type TEXT NOT NULL,
    canonical_label TEXT NOT NULL,
    summary_text TEXT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    authority_band TEXT NOT NULL DEFAULT 'seed',
    authority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 1,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_supported_at TIMESTAMPTZ NULL,
    last_contested_at TIMESTAMPTZ NULL,
    regime_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (
        node_type IN (
            'concept',
            'event',
            'forecast',
            'realized_data_point',
            'market_impact',
            'entity',
            'instrument',
            'open_question'
        )
    ),
    CHECK (status IN ('proposed', 'supported', 'reinforced', 'contested', 'stale', 'invalidated')),
    CHECK (authority_band IN ('seed', 'emerging', 'established', 'core', 'structural'))
);
```

Indexes:

- `idx_world_nodes_type_status` on `(node_type, status)`
- `idx_world_nodes_authority` on `authority_band`
- `idx_world_nodes_last_seen_at` on `last_seen_at`

## `world_node_aliases`

```sql
CREATE TABLE world_node_aliases (
    id BIGSERIAL PRIMARY KEY,
    world_node_id BIGINT NOT NULL REFERENCES world_nodes(id) ON DELETE CASCADE,
    alias_text TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    first_seen_research_id BIGINT NULL,
    last_seen_research_id BIGINT NULL,
    count_seen INTEGER NOT NULL DEFAULT 1
);
```

Constraints:

- unique on `(world_node_id, alias_text, alias_type)`

## `world_edges`

```sql
CREATE TABLE world_edges (
    id BIGSERIAL PRIMARY KEY,
    from_node_id BIGINT NOT NULL REFERENCES world_nodes(id) ON DELETE CASCADE,
    to_node_id BIGINT NOT NULL REFERENCES world_nodes(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    directionality TEXT NOT NULL DEFAULT 'directed',
    maturity TEXT NOT NULL DEFAULT 'trace',
    status TEXT NOT NULL DEFAULT 'proposed',
    authority_band TEXT NOT NULL DEFAULT 'seed',
    authority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 1,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_supported_at TIMESTAMPTZ NULL,
    last_contested_at TIMESTAMPTZ NULL,
    regime_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    explanation TEXT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (from_node_id <> to_node_id),
    CHECK (
        edge_type IN (
            'same_idea_as',
            'related_to',
            'supports',
            'contradicts',
            'qualifies',
            'drives',
            'implies',
            'reacts_to',
            'forecasts',
            'realized_as',
            'impacts',
            'raises_question'
        )
    ),
    CHECK (maturity IN ('trace', 'path', 'road', 'highway', 'structural')),
    CHECK (status IN ('proposed', 'supported', 'reinforced', 'contested', 'stale', 'invalidated')),
    CHECK (authority_band IN ('seed', 'emerging', 'established', 'core', 'structural'))
);
```

Constraints:

- unique on `(from_node_id, to_node_id, edge_type)`

Indexes:

- `idx_world_edges_type_status` on `(edge_type, status)`
- `idx_world_edges_authority` on `authority_band`
- `idx_world_edges_nodes` on `(from_node_id, to_node_id)`

## `world_node_evidence`

```sql
CREATE TABLE world_node_evidence (
    id BIGSERIAL PRIMARY KEY,
    world_node_id BIGINT NOT NULL REFERENCES world_nodes(id) ON DELETE CASCADE,
    assertion_id BIGINT NOT NULL REFERENCES analysis_assertions(id) ON DELETE CASCADE,
    evidence_unit_id BIGINT NULL REFERENCES analysis_evidence_units(id) ON DELETE SET NULL,
    research_id BIGINT NOT NULL,
    support_role TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Recommended uniqueness:

- unique on `(world_node_id, assertion_id, coalesce(evidence_unit_id, 0), support_role)`

## `world_edge_evidence`

```sql
CREATE TABLE world_edge_evidence (
    id BIGSERIAL PRIMARY KEY,
    world_edge_id BIGINT NOT NULL REFERENCES world_edges(id) ON DELETE CASCADE,
    assertion_id BIGINT NOT NULL REFERENCES analysis_assertions(id) ON DELETE CASCADE,
    evidence_unit_id BIGINT NULL REFERENCES analysis_evidence_units(id) ON DELETE SET NULL,
    research_id BIGINT NOT NULL,
    support_role TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Recommended uniqueness:

- unique on `(world_edge_id, assertion_id, coalesce(evidence_unit_id, 0), support_role)`

## `world_edge_history`

```sql
CREATE TABLE world_edge_history (
    id BIGSERIAL PRIMARY KEY,
    world_edge_id BIGINT NOT NULL REFERENCES world_edges(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    authority_band TEXT NOT NULL,
    authority_score DOUBLE PRECISION NOT NULL,
    support_count INTEGER NOT NULL,
    contradiction_count INTEGER NOT NULL,
    maturity TEXT NOT NULL,
    change_reason TEXT NOT NULL,
    trigger_research_id BIGINT NULL,
    CHECK (status IN ('proposed', 'supported', 'reinforced', 'contested', 'stale', 'invalidated')),
    CHECK (authority_band IN ('seed', 'emerging', 'established', 'core', 'structural')),
    CHECK (maturity IN ('trace', 'path', 'road', 'highway', 'structural'))
);
```

## Optional tables for later

### `analysis_backfill_jobs`

Recommended if manual reprocessing/backfills become frequent.

### `analysis_reviews`

Recommended when the review harness begins storing human judgments.

## Replacement and update rules

Intermediate document tables:

- safe to replace by `(research_id, document_hash, analysis_version)` as one atomic unit

World-model tables:

- should be updated and reinforced
- should not be wholesale deleted on rerun
- must be protected from double-counting by provenance uniqueness

## Open SQL decisions for implementation

- whether to use text-plus-checks or native enums
- whether `research_id` should also reference a mirrored `analysis_documents.id` surrogate everywhere
- whether `JSONB` fields should later split into normalized tag tables
- whether edge-history should exist for nodes as well in v1

## Recommended first implementation order

1. `analysis_runs`
2. `analysis_run_items`
3. `analysis_documents`
4. `analysis_chunks`
5. `analysis_evidence_units`
6. `analysis_assertions`
7. `analysis_assertion_evidence`
8. `world_nodes`
9. `world_node_aliases`
10. `world_edges`
11. `world_node_evidence`
12. `world_edge_evidence`
13. `world_edge_history`

## Acceptance criteria

This migration draft is sufficient when:

- another agent can translate it into actual SQL migrations with limited ambiguity
- uniqueness rules prevent duplicate support counting
- the schema supports both document replacement and long-lived graph evolution

## Related documents

- [2026-03-27-analysis-persistence-schema-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-persistence-schema-spec.md)
- [2026-03-27-world-model-resolution-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-world-model-resolution-spec.md)

## Status

`READY_FOR_SQL_TRANSLATION`
