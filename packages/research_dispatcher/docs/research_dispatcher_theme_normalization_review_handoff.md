# Research Dispatcher Theme Normalization Review Handoff

Last updated: 2026-03-22 America/New_York

## Scope

This note captures engineering concerns from reviewing:

- [research_dispatcher_theme_normalization_handoff.md](/Users/ncdial/devwork/research_parser/docs/research_dispatcher_theme_normalization_handoff.md)

The goal is to make the migration work safely in `research_dispatcher`, which is still built around document-shaped `parsed_data` records today.

## Current dispatcher assumptions

`research_dispatcher` is still centered on `parsed_research.parsed_data`:

- Query filters read metadata from JSONB in [src/database.py:43](/Users/ncdial/devwork/research_dispatcher/src/database.py#L43) and [src/database.py:48](/Users/ncdial/devwork/research_dispatcher/src/database.py#L48)
- Report summary/details read publisher, themes, and trades from JSONB in [src/formatter.py:95](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L95), [src/formatter.py:115](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L115), and [src/formatter.py:145](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L145)
- Synthesis input extraction reads themes and trades directly from `parsed_data` in [src/synthesizer.py:1191](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py#L1191) and [src/synthesizer.py:1234](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py#L1234)

Because of that, any normalized-read migration needs a compatibility boundary instead of a flat query swap.

## Findings

### 1. `document_hash` is not a strong enough gate for normalized reads

The reviewed handoff suggests using:

- `document_hash IS NOT NULL`
- or `document_hash IS NOT NULL AND theme_count > 0`

See [research_dispatcher_theme_normalization_handoff.md:84](/Users/ncdial/devwork/research_parser/docs/research_dispatcher_theme_normalization_handoff.md#L84) and [research_dispatcher_theme_normalization_handoff.md:90](/Users/ncdial/devwork/research_parser/docs/research_dispatcher_theme_normalization_handoff.md#L90).

That is too weak for `research_dispatcher`.

Why:

- The parser writes the parent `parsed_research` row first in [supabase.py:105](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L105)
- Normalized theme replacement happens later in [supabase.py:123](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L123) and [supabase.py:162](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L162)

So a row can have `document_hash` and `theme_count` populated while normalized child rows are missing or partial.

Recommendation:

- Gate on actual normalized child presence, not just parent flags
- Prefer a left-joined normalized theme count
- Only trust normalized themes when normalized child count matches the expected count
- Fall back to `parsed_data.themes` otherwise

Practical rule:

- Use normalized theme rows only when `document_hash IS NOT NULL` and `count(research_themes.id) = parsed_research.theme_count`

## 2. The suggested join shape will duplicate rows unless dispatcher re-aggregates first

The reviewed handoff recommends joining:

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`

See [research_dispatcher_theme_normalization_handoff.md:92](/Users/ncdial/devwork/research_parser/docs/research_dispatcher_theme_normalization_handoff.md#L92).

That query shape is not directly compatible with this codebase.

Why:

- Dispatcher logic expects one document record per `parsed_research` row
- Themes are currently consumed as nested arrays, not as flat joined rows
- Joining excerpts multiplies rows per theme and will inflate counts unless re-grouped

Relevant consumers:

- [src/synthesizer.py:1190](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py#L1190)
- [src/formatter.py:114](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L114)
- [src/formatter.py:144](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L144)

Recommendation:

- Introduce a compatibility adapter in the fetch layer
- Return one document-shaped object per `parsed_research` row
- Reconstruct normalized themes as nested arrays before they reach formatter/synthesizer code

The first migration step should be:

- change the database access layer, not the downstream consumers

## 3. Metadata migration is underspecified even though dispatcher depends on it

The reviewed handoff focuses on theme normalization, but this repo also depends on metadata reads and filters that still point at JSONB.

Current dependencies:

- region filter from JSONB in [src/database.py:43](/Users/ncdial/devwork/research_dispatcher/src/database.py#L43)
- asset focus filter from JSONB in [src/database.py:48](/Users/ncdial/devwork/research_dispatcher/src/database.py#L48)
- publisher display from JSONB in [src/formatter.py:95](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L95) and [src/formatter.py:125](/Users/ncdial/devwork/research_dispatcher/src/formatter.py#L125)

But the normalized schema already added document-level columns in:

- [001_theme_normalization_schema.sql:9](/Users/ncdial/devwork/research_parser/migrations/001_theme_normalization_schema.sql#L9)

Those include:

- `publisher`
- `area`
- `region`
- `asset_focus`
- `document_link`

Recommendation:

- Make metadata migration explicit in the plan
- Move dispatcher filters to top-level columns first
- Keep `parsed_data.metadata` only as a fallback during mixed-mode rollout if needed

## 4. Mixed-mode reads are only defined for themes, not for trades

The reviewed handoff gives a mixed-mode read strategy for themes, but `research_dispatcher` synthesis still needs trades from every document.

Trade extraction is still JSONB-only in:

- [src/synthesizer.py:1234](/Users/ncdial/devwork/research_dispatcher/src/synthesizer.py#L1234)

This normalization rollout did not add normalized trade tables. The live parser still stores trades in `parsed_data` as part of the archival payload in:

- [supabase.py:49](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L49)

Recommendation:

- State the mixed-mode contract explicitly:
- metadata from top-level document columns
- themes from normalized tables when verified
- trades from `parsed_data.trades` for all rows

Without this, the migration plan is incomplete for the actual synthesis pipeline.

## 5. `research_theme_links` exists in schema but should remain out of the parser path

The reviewed handoff lists `research_theme_links` as a normalized table in:

- [research_dispatcher_theme_normalization_handoff.md:31](/Users/ncdial/devwork/research_parser/docs/research_dispatcher_theme_normalization_handoff.md#L31)

The parser docstring also says dual-write covers it in:

- [supabase.py:39](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L39)

But the current live write path only replaces:

- `research_themes`
- `research_theme_excerpts`

See:

- [supabase.py:123](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L123)
- [supabase.py:162](/Users/ncdial/devwork/research_parser/src/storage/supabase.py#L162)
- [backfill_theme_normalization.py:270](/Users/ncdial/devwork/research_parser/scripts/backfill_theme_normalization.py#L270)

Recommendation:

- Treat `research_theme_links` as deferred schema for now
- Do not add link population to the parser or theme backfill path
- If related-theme inference is needed, compute it downstream from normalized theme rows after ingestion

Architecture decision:

- parsing should extract document-local facts only
- relationship inference should happen in a separate downstream enrichment process

Why:

- it keeps parsing deterministic and lower-risk
- it avoids forcing a single-document parser to infer higher-order relationships
- it leaves cross-document or graph-style linkage to the system that actually consumes it

## Recommended implementation sequence

1. Add a compatibility read layer in `src/database.py` that returns one document-shaped object per `parsed_research` row.
2. Move region, asset focus, and publisher reads to top-level columns with fallback only if necessary.
3. Build normalized-theme hydration that reconstructs theme arrays from relational rows.
4. Gate normalized theme use on verified child coverage, not only `document_hash`.
5. Leave trades on `parsed_data.trades` for now.
6. Add tests for mixed-mode records:
   - legacy row with JSONB-only themes
   - fully normalized row
   - row with `document_hash` populated but missing normalized children
   - row with partial excerpt/theme data

## Open questions

1. Should `parsed_data.metadata` remain a long-term fallback, or should dispatcher fully switch to top-level metadata columns in this migration?
2. Do we want the first implementation step to be a narrow database compatibility refactor, or a broader end-to-end payload refactor?

## Status

`DONE_WITH_CONCERNS`
