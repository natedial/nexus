# Theme Normalization Migration Plan

Last updated: 2026-03-22 America/New_York

## Goal

Move `research_dispatcher` onto the new normalized theme storage without breaking the current formatter and synthesis pipeline.

The migration should:

- use top-level document columns for document metadata where available
- use normalized theme tables when the normalized child data is complete
- fall back to `parsed_data` for legacy or partial rows
- keep trades, through-lines, and callouts on the current `parsed_data` path for now

## Recommendation

Use a compatibility-layer migration first.

Opinionated recommendation:

- Keep the downstream contract unchanged in phase 1
- Do the mixed-mode logic entirely in `src/database.py`
- Return records that still look like current `parsed_research` rows, but with `parsed_data["themes"]` hydrated from normalized tables when safe

Why this is the right first move:

- it isolates the migration to the fetch boundary
- it avoids a broad formatter/synthesizer refactor
- it lets us validate normalized reads without changing PDF or synthesis behavior at the same time

Tradeoff:

- this temporarily keeps some compatibility code in the database layer
- that is acceptable because it reduces blast radius during schema transition

## Non-Goals

This plan does not include:

- normalized trade storage
- changing the PDF layout
- using `research_theme_links`
- removing `parsed_data` archival storage
- parser-time related-theme inference

## Current Constraints

`research_dispatcher` currently assumes one document-shaped record per row and reads directly from `parsed_data`:

- query/filter entry point in [src/database.py](/Users/ncdial/devwork/research_dispatcher/src/database.py)
- report aggregation in [src/formatter.py](/Users/ncdial/devwork/research_dispatcher/src/formatter.py)
- synthesis input extraction in [src/synthesizer.py](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py)

The parser rollout added:

- top-level metadata columns on `parsed_research`
- normalized theme rows in `research_themes`
- normalized excerpts in `research_theme_excerpts`

See:

- [001_theme_normalization_schema.sql](/Users/ncdial/devwork/research_parser/migrations/001_theme_normalization_schema.sql)
- [supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py)

## Target Contract

`DatabaseClient.query_analysis()` should keep returning one document-shaped dict per selected `parsed_research` row.

The returned object should preserve:

- top-level row fields like `id`, `source`, `source_date`, `synthesized`
- `parsed_data` with:
  - `metadata`
  - `themes`
  - `trades`
  - `through_lines`
  - `callouts`

But the contents should be resolved as follows:

- `metadata`
  - prefer top-level columns: `publisher`, `area`, `region`, `asset_focus`, `document_link`
  - fall back to `parsed_data.metadata`
- `themes`
  - prefer normalized theme hydration when verified complete
  - otherwise use `parsed_data.themes`
- `trades`
  - keep using `parsed_data.trades`
- `through_lines`
  - keep using `parsed_data.through_lines`
- `callouts`
  - keep using `parsed_data.callouts`

This keeps formatter and synthesizer behavior stable while the storage backend changes.

## Completeness Rules

### Metadata completeness

For each row, derive effective metadata from:

1. top-level columns if present and non-empty
2. otherwise `parsed_data.metadata`

### Theme completeness

For each row, use normalized themes only when both are true:

1. `document_hash` is non-null
2. normalized theme count equals `parsed_research.theme_count`

If either condition fails:

- use `parsed_data.themes`

Reason:

- `document_hash` alone is not enough
- the parser writes the parent row before replacing normalized children

## Query Strategy

Do not switch to a single flat join query.

Opinionated recommendation:

- fetch candidate `parsed_research` rows first
- fetch normalized theme rows in a second batch query by `research_id`
- fetch excerpt rows in a third batch query by normalized `theme_id`
- hydrate normalized themes in Python

Why:

- avoids row duplication from joining excerpts
- avoids rewriting downstream consumers to understand flat joined rows
- avoids N+1 requests if implemented in batches

### Candidate row query

Continue querying `parsed_research` as the base table with:

- `source_date`
- `synthesized`
- optional `source`

For region and asset-focus during mixed-mode rollout:

- fetch the date/source candidate set first
- apply region and asset-focus filtering in Python using resolved metadata

Opinionated recommendation:

- do not fight PostgREST with mixed top-level-plus-JSON fallback filters for this phase
- the dispatcher date window is already bounded, so Python-side filtering is the safer migration path

Tradeoff:

- more rows may be fetched than strictly necessary
- but the logic is much simpler and correctness matters more than micro-optimizing this boundary

## Implementation Phases

## Phase 1: Add compatibility hydration in `src/database.py`

Files:

- [src/database.py](/Users/ncdial/devwork/research_dispatcher/src/database.py)

Tasks:

- add a helper that resolves effective metadata from top-level columns plus JSON fallback
- add a helper that fetches normalized themes for a list of `parsed_research.id` values
- add a helper that fetches excerpts for normalized theme ids
- add a helper that converts normalized rows back into the legacy theme dict shape expected downstream
- add a helper that decides whether a row is safe for normalized theme use
- update `query_analysis()` to:
  - fetch base rows
  - hydrate normalized themes in batch
  - merge resolved metadata into `parsed_data["metadata"]`
  - replace `parsed_data["themes"]` only when the row passes the completeness check
  - apply region and asset-focus filters against resolved metadata

Acceptance criteria:

- `query_analysis()` still returns document-shaped records
- callers do not need to know whether themes came from normalized rows or JSONB
- a partial normalized row does not break the report

## Phase 2: Keep downstream consumers stable, then tighten assumptions

Files:

- [src/formatter.py](/Users/ncdial/devwork/research_dispatcher/src/formatter.py)
- [src/synthesizer.py](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py)

Tasks:

- make only minimal defensive changes if needed
- avoid broad refactors in this phase
- verify that counts, grouping, and synthesis input still work with hydrated theme dicts

Opinionated recommendation:

- do not rewrite formatter and synthesizer to read normalized tables directly yet
- keep them consuming the same shape they consume today

Acceptance criteria:

- `themes_analysis` output remains stable
- synthesis input still contains source-tagged themes and trades
- no change is required in `src/main.py`

## Phase 3: Add test coverage for mixed-mode rows

Files:

- add [tests/test_database_theme_normalization.py](/Users/ncdial/devwork/research_dispatcher/tests/test_database_theme_normalization.py)
- extend existing formatter/synthesizer tests only if necessary

Test cases:

1. legacy row
   - `parsed_data.themes` present
   - `document_hash` null
   - no normalized rows
   - expected: JSON themes used

2. fully normalized row
   - `document_hash` present
   - `theme_count` matches normalized child count
   - excerpts present
   - expected: normalized themes hydrated into legacy theme shape

3. partial normalized row
   - `document_hash` present
   - `theme_count` greater than normalized child count
   - expected: fallback to `parsed_data.themes`

4. metadata fallback row
   - top-level `region` or `asset_focus` missing
   - JSON metadata present
   - expected: filter logic still includes/excludes correctly

5. metadata precedence row
   - both top-level and JSON metadata present but differ
   - expected: top-level values win

6. no-theme row
   - zero themes in both places
   - expected: no failure, no false normalization signal

Acceptance criteria:

- mixed-mode hydration logic is covered directly
- failure modes are covered explicitly
- tests do not require live Supabase access

## Phase 4: Update docs and schema expectations

Files:

- [README.md](/Users/ncdial/devwork/research_dispatcher/README.md)
- optional follow-up note in [docs/research_dispatcher_theme_normalization_review_handoff.md](/Users/ncdial/devwork/research_dispatcher/docs/research_dispatcher_theme_normalization_review_handoff.md)

Tasks:

- update the database schema section to reflect mixed-mode reads
- document that trades still come from `parsed_data`
- document that top-level metadata columns are now preferred

Acceptance criteria:

- repo docs match actual runtime behavior

## Proposed Data Mapping

### Normalized theme row to legacy theme dict

Recommended mapping:

- `label` <- `research_themes.label`
- `context` <- `research_themes.context`
- `strength` <- `research_themes.strength`
- `confidence` <- `research_themes.confidence`
- `classification` <- `research_themes.classification`
- `mention_count` <- `research_themes.mention_count`
- `relevance` <- `research_themes.relevance`
- `directionality` <- `research_themes.directionality`
- `excerpts` <- ordered list from `research_theme_excerpts`

Optional for parity if available:

- include `evidence_count`
- include `argument_structure`

Opinionated recommendation:

- preserve field names that current formatter/synthesizer already know
- do not invent a new downstream theme schema in this migration

## Decision Points

### Decision 1: Where should mixed-mode logic live?

Options:

- database compatibility layer
- downstream formatter/synthesizer refactor

Recommendation:

- choose the database compatibility layer

Reason:

- smallest blast radius
- easiest to test
- easiest to roll back

### Decision 2: How should metadata filtering work during rollout?

Options:

- complex DB-side mixed OR filtering across top-level and JSON fields
- Python-side filtering after fetching a bounded candidate set

Recommendation:

- use Python-side filtering in this phase

Reason:

- simpler
- less brittle
- easier to verify for mixed-mode rows

### Decision 3: Should we use `research_theme_links` now?

Options:

- incorporate it into hydration
- ignore it until parser writes it

Recommendation:

- ignore it for now

Reason:

- the schema exists, but current write paths do not appear to populate it
- related-theme inference is a downstream enrichment concern, not a single-document parsing concern

Architectural rule:

- parser responsibilities:
  - `parsed_research`
  - `research_themes`
  - `research_theme_excerpts`
- downstream responsibilities:
  - related-theme inference
  - cross-document linkage
  - any future population of `research_theme_links`

## Rollout Plan

1. Land database hydration helpers and tests first.
2. Run unit tests locally.
3. Run a non-production report generation flow against a small date window.
4. Validate that:
   - filtered document counts look correct
   - theme counts in the PDF match expected source rows
   - synthesis still runs without schema-specific changes
5. Only then consider any cleanup refactor in formatter/synthesizer.

## Validation Checklist

- legacy rows still appear in reports
- normalized rows use normalized themes
- partial normalized rows fall back correctly
- region and asset-focus filters behave correctly for both old and new rows
- synthesis sees the same effective theme/trade payload shape as before
- no duplicate theme inflation from excerpt joins

## Suggested Work Breakdown

1. Implement database compatibility helpers.
2. Add mixed-mode unit tests.
3. Run and fix formatter/synthesizer regressions if any appear.
4. Update README.

## Status

`DONE_WITH_CONCERNS`
