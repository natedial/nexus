# Theme Extraction Quality and Queryability Enhancement Proposal

**Date:** 2026-03-21  
**Status:** Draft  
**Impact:** High - improves extraction depth and makes theme/link data directly queryable by `sophia_engine`

## Executive Summary

Current theme extraction is optimized for producing a compact JSON payload inside `parsed_data`. That is useful as an archival record, but it is a weak querying surface for an agent that needs to ask questions like:

- Which documents argue that energy shocks drive inflation persistence?
- What themes most often contradict a soft-landing view?
- Which documents connect Fed reaction function risk to USD strength?
- What conditional forecasts recur across publishers and dates?

This proposal keeps `parsed_data` as the canonical archival payload but adds a normalized relational layer for queryability. The result is a dual-write design:

- `parsed_data` remains the full raw extraction payload for debugging, replay, and backward compatibility
- New relational tables become the primary query surface for `sophia_engine`

The proposal also tightens prompt quality so extracted themes contain more analytical depth before they are persisted.

## Problem Statement

### Current Strengths

- Theme extraction already produces structured theme objects with excerpts and summaries
- The pipeline is resilient to partial failures
- Existing storage is simple and backward compatible

### Current Limitations

1. Theme data is nested inside `parsed_data`, which makes agent querying awkward and expensive.
2. Inter-theme relationships are not stored as first-class entities.
3. Current `context` is too shallow for strong downstream reasoning.
4. Chunked extraction merges themes by label after model calls, so any future linkage fields must be resolved after merge, not trusted directly from chunk-local output.
5. The proposal to add a `themes_v2` JSON blob does not fit the current storage model, because this service stores themes inside `parsed_data`, not in a top-level `themes` column.

## Goals

1. Increase analytical depth of extracted themes.
2. Preserve backward compatibility for existing consumers of `parsed_data`.
3. Make themes, excerpts, and linkages directly queryable in Supabase.
4. Support `sophia_engine` queries without requiring JSON traversal as the primary access pattern.
5. Keep rollout incremental so prompt improvements and schema changes can be validated separately.

## Non-Goals

- Replacing `parsed_data` as the archival source of truth
- Building full cross-document synthesis inside this service
- Introducing embeddings or vector search in this phase
- Refactoring the entire extraction pipeline away from chunked extraction

## Recommended Architecture

### Core Principle

Use two storage surfaces with different purposes:

- `parsed_data`: archival payload, full fidelity, backward compatible, good for debugging
- Relational tables: normalized, indexed, queryable, good for agents and analytics

### Why This Is Better Than `themes_v2`

Adding another JSON blob such as `themes_v2` would still leave `sophia_engine` querying nested structures. That helps schema evolution but does not materially improve query ergonomics. If the goal is agent querying, the right unit is rows and foreign keys, not deeper JSON.

### Storage Model

Keep `parsed_research` as the document table, and add normalized theme tables:

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`
- `research_theme_links`

Optionally add a small number of document-level columns on `parsed_research` for frequent filters.

## Proposed Changes

### Change 1: Expand `context` Into a Structured Analytical Narrative

**Current:** short, often generic sentence  
**Proposed:** 3-5 sentences capturing thesis, transmission, and implications

**Updated Prompt Language**

```text
"context": "3-5 sentences capturing:
  1) THESIS: the core analytical claim or primary driver
  2) TRANSMISSION: how this propagates through markets, sectors, or the economy
  3) IMPLICATIONS: specific policy, positioning, risk, or market consequences

  Example GOOD context: 'Energy supply shock is identified as a near-term driver for cost-push inflation. Energy costs form the first wave, but downstream impacts in fertilizer, chemicals, medicines, plastics, and manufacturing inputs see passthroughs. This is expected to be longer-lasting and difficult for central banks to interpret cleanly, increasing the odds of hawkish pauses.'

  Example BAD context: 'Energy prices are rising due to geopolitical risk.'"
```

**Implementation**

- Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md)
- No schema change required for Phase 1

### Change 2: Increase Excerpt Limits and Add a Substantive Evidence Gate

**Current:** 40-word max excerpts  
**Proposed:** 80-100-word max excerpts when needed to preserve a full analytical claim

**Updated Prompt Language**

```text
"excerpts": [
  {"text": "verbatim quote from the document (80-100 words max). Prefer a complete analytical claim with reasoning, not a topic fragment."}
]
```

**New Quality Rule**

```text
At least 50% of Primary themes must include at least one excerpt containing:
- a conditional forecast, or
- a causal mechanism, or
- a cross-asset or market implication
```

**Implementation**

- Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md)
- Add resilience tests for longer excerpts in [tests/test_themes_resilience.py](/Users/ncdial/devwork/research_parser/tests/test_themes_resilience.py)

### Change 3: Add Analytical Depth as a Mandatory Prompt Gate

**Current gates:** coverage, no orphan sections, evidence density, stability  
**Proposed:** add analytical depth

**New Gate**

```text
Analytical depth: at least 60% of Primary themes must show one of:
- a transmission mechanism
- a conditional forecast with triggers
- a cross-asset or policy implication tied to the thesis
```

**Implementation Notes**

- This improves model behavior, but prompt gates alone are not enough
- The extractor currently only returns final `Theme` objects, so coverage/audit metadata should be explicitly preserved if we want to inspect gate performance later

### Change 4: Add `argument_structure` to Theme Output

**Current:** `classification` alone is too coarse  
**Proposed:** keep `classification`, add a richer `argument_structure`

**Schema Shape**

```json
{
  "classification": "Opinion|Forecast|Description",
  "argument_structure": {
    "conditionals": ["explicit IF/THEN or trigger clauses from the text"],
    "confidence_basis": "stated basis for conviction",
    "dependencies": ["factors or other themes the thesis relies on"],
    "contradictions": ["explicit hedges, tensions, or opposing cases"]
  }
}
```

**Important Constraint**

This field should be merged after chunk extraction. The current extractor merges per-chunk themes by normalized label, so any new field must define merge rules in [src/extraction/themes.py](/Users/ncdial/devwork/research_parser/src/extraction/themes.py).

### Change 5: Add Explicit Theme Interconnections

**Current:** themes are stored as isolated objects  
**Proposed:** represent explicit relationships as first-class rows

**Logical Output Shape**

```json
{
  "interconnections": [
    {
      "related_theme": "label of another theme in this document",
      "relationship": "drives|amplifies|contradicts|hedges|enables",
      "explanation": "author's explicit statement of how they relate"
    }
  ]
}
```

**Storage Recommendation**

Do not rely on storing only `related_theme` labels in Supabase. Labels are unstable after merge. Instead:

- extract tentative label-based relationships from the model
- resolve them after final theme merge
- persist resolved links using theme IDs in `research_theme_links`

## Proposed Supabase Schema

### Keep `parsed_research` as the document table

Continue storing:

- `parsed_data JSONB`
- `source_date`
- `source`
- `document_name`

Add query-friendly document columns:

- `document_title TEXT NULL`
- `publisher TEXT NULL`
- `area TEXT NULL`
- `region TEXT NULL`
- `asset_focus TEXT NULL`
- `document_link TEXT NULL`
- `theme_count INTEGER NOT NULL DEFAULT 0`
- `trade_count INTEGER NOT NULL DEFAULT 0`

### New Table: `research_themes`

One row per final merged theme for a document.

```sql
create table research_themes (
    id bigserial primary key,
    research_id bigint not null references parsed_research(id) on delete cascade,
    theme_order integer not null,
    label text not null,
    scope text null,
    primary_category text null,
    relevance text[] not null default '{}',
    classification text not null,
    strength text not null,
    confidence text not null,
    evidence_count integer not null default 0,
    mention_count integer not null default 0,
    context text not null default '',
    directionality jsonb null,
    argument_structure jsonb null,
    created_at timestamptz not null default now()
);

create index research_themes_research_id_idx on research_themes(research_id);
create index research_themes_label_idx on research_themes(label);
create index research_themes_primary_category_idx on research_themes(primary_category);
create index research_themes_strength_idx on research_themes(strength);
```

### New Table: `research_theme_excerpts`

One row per excerpt.

```sql
create table research_theme_excerpts (
    id bigserial primary key,
    theme_id bigint not null references research_themes(id) on delete cascade,
    excerpt_order integer not null,
    excerpt_text text not null
);

create index research_theme_excerpts_theme_id_idx on research_theme_excerpts(theme_id);
```

### New Table: `research_theme_links`

One row per explicit relationship between two themes in the same document.

```sql
create table research_theme_links (
    id bigserial primary key,
    research_id bigint not null references parsed_research(id) on delete cascade,
    from_theme_id bigint not null references research_themes(id) on delete cascade,
    to_theme_id bigint not null references research_themes(id) on delete cascade,
    relationship text not null,
    explanation text not null,
    created_at timestamptz not null default now(),
    check (from_theme_id <> to_theme_id)
);

create index research_theme_links_research_id_idx on research_theme_links(research_id);
create index research_theme_links_from_theme_id_idx on research_theme_links(from_theme_id);
create index research_theme_links_to_theme_id_idx on research_theme_links(to_theme_id);
create index research_theme_links_relationship_idx on research_theme_links(relationship);
```

## Agent Query Benefits

This schema supports much cleaner queries for `sophia_engine`.

### Example: Find documents linking inflation persistence to energy shocks

```sql
select pr.id, pr.source, pr.source_date, rt.label, rt.context
from parsed_research pr
join research_themes rt on rt.research_id = pr.id
where rt.label ilike '%inflation%'
  and rt.context ilike '%energy%';
```

### Example: Find explicit contradictions to a soft-landing thesis

```sql
select pr.source, pr.source_date, t1.label as from_theme, t2.label as to_theme, l.explanation
from research_theme_links l
join parsed_research pr on pr.id = l.research_id
join research_themes t1 on t1.id = l.from_theme_id
join research_themes t2 on t2.id = l.to_theme_id
where l.relationship = 'contradicts'
  and t2.label ilike '%soft landing%';
```

### Example: Pull conditional forecasts for a macro category

```sql
select pr.source, pr.source_date, rt.label, rt.argument_structure
from parsed_research pr
join research_themes rt on rt.research_id = pr.id
where rt.primary_category = 'Macro'
  and rt.argument_structure is not null;
```

## Implementation Plan

### Phase 1: Prompt Quality Improvements

**Scope**

- Expand `context`
- Increase excerpt room
- Add analytical depth guidance

**Code Changes**

- Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md)

**Tests**

1. Extend [tests/test_themes_resilience.py](/Users/ncdial/devwork/research_parser/tests/test_themes_resilience.py) for longer excerpts and optional richer fields
2. Use [scripts/compare_theme_models.py](/Users/ncdial/devwork/research_parser/scripts/compare_theme_models.py) or [scripts/evaluate_theme_quality.py](/Users/ncdial/devwork/research_parser/scripts/evaluate_theme_quality.py) on a fixed set of sample documents
3. Manually review at least 10 documents for depth, not just 5

**Go/No-Go Criteria**

- Contexts are materially more explanatory, not just longer
- No significant increase in parse failures
- Primary themes more often include mechanisms, conditions, or implications

### Phase 2: Internal Theme Schema Upgrade

**Scope**

- Add `argument_structure` to `Theme`
- Add an internal representation for extracted link candidates
- Define deterministic merge behavior for new fields

**Code Changes**

- Update [src/extraction/models.py](/Users/ncdial/devwork/research_parser/src/extraction/models.py)
- Update [src/extraction/themes.py](/Users/ncdial/devwork/research_parser/src/extraction/themes.py)
- Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md)

**Required Merge Rules**

- `conditionals`: ordered union, deduplicated
- `dependencies`: ordered union, deduplicated
- `contradictions`: ordered union, deduplicated
- `confidence_basis`: prefer the more specific non-empty value
- `interconnections`: store as unresolved label references until final merged theme IDs are known

**Tests**

1. Chunked extraction test with new fields
2. Merge test for duplicate theme labels across chunks
3. Backward compatibility test where new fields are absent

### Phase 3: Supabase Schema Expansion

**Scope**

- Add query-friendly columns to `parsed_research`
- Create normalized theme tables

**Migration Strategy**

1. Add new nullable columns to `parsed_research`
2. Create `research_themes`, `research_theme_excerpts`, and `research_theme_links`
3. Deploy schema before code
4. Keep existing `parsed_data` writes unchanged during rollout

**Recommended DDL**

```sql
alter table parsed_research
    add column if not exists document_title text null,
    add column if not exists publisher text null,
    add column if not exists area text null,
    add column if not exists region text null,
    add column if not exists asset_focus text null,
    add column if not exists document_link text null,
    add column if not exists theme_count integer not null default 0,
    add column if not exists trade_count integer not null default 0;
```

Then create the three normalized tables shown above.

### Phase 4: Pipeline Dual-Write

**Scope**

- Continue writing `parsed_data`
- Also write normalized rows after the `parsed_research` insert succeeds

**Code Changes**

- Update [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py)
- Potentially introduce a storage helper module if write logic becomes too large

**Recommended Write Order**

1. Insert document row into `parsed_research`
2. Get inserted `research_id`
3. Insert normalized theme rows
4. Insert excerpts
5. Resolve and insert theme links

**Important Constraint**

Link resolution should happen after final theme merge, not per chunk.

### Phase 5: Backfill Existing Records

**Scope**

- Normalize already-stored documents from existing `parsed_data`

**Approach**

Write a one-off backfill script that:

1. Reads `parsed_research.id` and `parsed_data`
2. Extracts metadata and themes from `parsed_data`
3. Inserts rows into `research_themes` and `research_theme_excerpts`
4. Leaves `research_theme_links` empty for legacy records unless reliable links can be reconstructed

**Recommendation**

Do not attempt to infer missing links during backfill. Only backfill fields that are already present.

### Phase 6: Production Validation

**Shadow Validation**

1. Run dual-write on staging
2. Process at least 50 documents
3. Validate:
   - `parsed_data` still looks correct
   - normalized counts match payload counts
   - theme links only appear where explicitly supported

**Rollout**

1. Deploy schema
2. Deploy code with dual-write
3. Backfill historical records
4. Point `sophia_engine` queries to normalized tables

## Testing Plan

### Unit Tests

- Theme model accepts new optional fields
- Theme merge behavior is deterministic
- Link resolution maps labels to final theme IDs
- Supabase writer inserts normalized rows in the expected order

### Integration Tests

- End-to-end extraction writes both `parsed_data` and normalized rows
- Documents without new fields still store correctly
- Chunked documents preserve merged theme semantics

### Evaluation Harness

Use a fixed benchmark set and compare:

- average context length
- percentage of primary themes with mechanisms
- percentage with conditional forecasts
- parse failure rate
- link precision on a hand-reviewed sample

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Avg context quality | shallow/inconsistent | materially explanatory |
| % primary themes with mechanism or conditional | low | 60%+ |
| Theme data queryable without JSON traversal | no | yes |
| Explicit theme links queryable by join | no | yes |
| Backward compatibility for `parsed_data` consumers | yes | maintained |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Longer excerpts increase token cost | Medium | Medium | monitor usage, cap excerpt count |
| New fields reduce parse reliability | Medium | High | keep fields optional, add resilience tests |
| Theme links hallucinate relationships | Medium | High | require explicit textual basis, review sampled outputs |
| Dual-write introduces storage bugs | Medium | High | stage rollout, add integration tests, preserve archival write path |
| Backfill duplicates normalized rows | Medium | Medium | use idempotent script keyed by `research_id` |

## Recommendation

Approve a revised implementation with this sequence:

1. Prompt quality improvements first
2. Internal schema and merge semantics second
3. Supabase relational schema third
4. Dual-write and backfill last

This gives `sophia_engine` a real query surface without breaking existing consumers or overloading `parsed_data` with responsibilities it is not well suited to serve.

## Implementation Checklist

### Phase 1: Prompt Quality

- [ ] Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md) to expand `context` into a thesis/mechanism/implications narrative
- [ ] Update [prompts/themes.md](/Users/ncdial/devwork/research_parser/prompts/themes.md) to allow longer excerpts when needed for full analytical claims
- [ ] Add prompt guidance for analytical-depth gating
- [ ] Extend [tests/test_themes_resilience.py](/Users/ncdial/devwork/research_parser/tests/test_themes_resilience.py) for longer excerpts and richer optional output
- [ ] Run benchmark comparisons with [scripts/compare_theme_models.py](/Users/ncdial/devwork/research_parser/scripts/compare_theme_models.py)
- [ ] Review at least 10 representative documents manually
- [ ] Decide whether prompt quality is good enough to proceed to schema work

### Phase 2: Internal Extraction Schema

- [ ] Add `ArgumentStructure` model(s) in [src/extraction/models.py](/Users/ncdial/devwork/research_parser/src/extraction/models.py)
- [ ] Add internal representation for extracted inter-theme link candidates
- [ ] Update [src/extraction/themes.py](/Users/ncdial/devwork/research_parser/src/extraction/themes.py) response schema to accept new fields
- [ ] Define deterministic merge rules for `argument_structure`
- [ ] Define deterministic merge rules for unresolved interconnections
- [ ] Add chunk-merge tests covering duplicate theme labels across chunks
- [ ] Add backward-compatibility tests for records without new fields

### Phase 3: Supabase Schema

- [ ] Add query-friendly columns to `parsed_research`
- [ ] Create `research_themes`
- [ ] Create `research_theme_excerpts`
- [ ] Create `research_theme_links`
- [ ] Add indexes for common filters and joins
- [ ] Review the DDL against actual Supabase constraints and permissions
- [ ] Apply schema changes in staging first

### Phase 4: Pipeline Dual-Write

- [ ] Update [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py) to write new document-level columns
- [ ] Insert normalized theme rows after the `parsed_research` insert succeeds
- [ ] Insert excerpt rows for each stored theme
- [ ] Resolve link candidates against final merged theme IDs
- [ ] Insert resolved rows into `research_theme_links`
- [ ] Keep `parsed_data` output unchanged for backward compatibility
- [ ] Add storage-layer tests for dual-write behavior

### Phase 5: Backfill

- [ ] Create a one-off backfill script for historical `parsed_research` rows
- [ ] Populate `research_themes` from existing `parsed_data`
- [ ] Populate `research_theme_excerpts` from existing `parsed_data`
- [ ] Leave `research_theme_links` empty where no reliable explicit link data exists
- [ ] Make the backfill idempotent by `research_id`
- [ ] Run backfill on staging and verify row counts before production

### Phase 6: Validation and Rollout

- [ ] Validate that normalized theme counts match `parsed_data` counts
- [ ] Validate that theme links are only stored when explicitly supported
- [ ] Confirm no regression in parse/storage failure rates
- [ ] Confirm `sophia_engine` can answer representative queries from normalized tables
- [ ] Roll out schema and code to production
- [ ] Run production backfill
- [ ] Switch agent queries from JSON traversal to normalized tables
- [ ] Monitor for migration, storage, and query regressions

### Decisions To Lock

- [ ] Decide whether to store `primary_category` separately from `relevance`
- [ ] Decide whether `scope` should remain free-text or be normalized
- [ ] Decide whether `relationship` values need a constrained enum in SQL
- [ ] Decide whether to persist coverage/audit metadata for prompt-gate observability
- [ ] Decide whether legacy rows should ever receive inferred links in a later phase

## Decision Required

**Approver:** ___  
**Date:** ___

- [ ] Approve Phase 1 only
- [ ] Approve Phases 1-4
- [ ] Approve full plan including backfill
- [ ] Request modifications
- [ ] Reject

**Additional Notes:**
