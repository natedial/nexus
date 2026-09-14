# Research Dispatcher Theme Normalization Handoff

Last updated: 2026-03-22 America/New_York

## What shipped

The theme normalization schema has been deployed to Supabase and the parser has been redeployed with dual-write enabled.

The deployed schema comes from:

- [migrations/001_theme_normalization_schema.sql](/Users/ncdial/devwork/research_parser/migrations/001_theme_normalization_schema.sql)

The live write path is in:

- [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py)

## Live schema

`parsed_research` now includes these new columns:

- `document_title`
- `publisher`
- `area`
- `region`
- `asset_focus`
- `document_link`
- `theme_count`
- `trade_count`
- `document_hash`

The following normalized tables now exist:

- `research_themes`
- `research_theme_excerpts`
- `research_theme_links`

Important current limitation:

- `research_theme_links` exists in schema only.
- The live writer in [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py) currently writes `research_themes` and `research_theme_excerpts`, but does not insert rows into `research_theme_links`.
- The current backfill script in [scripts/backfill_theme_normalization.py](/Users/ncdial/devwork/research_parser/scripts/backfill_theme_normalization.py) also rebuilds only `research_themes` and `research_theme_excerpts`.

## What was verified in production

Before schema rollout, a local row-level backup of `parsed_research` was taken and kept out of the repository.

After deploying the schema and redeploying the parser, a canary reprocessing test was run for:

- `2026-03-22_JPM_US_Derivatives__It_starts_with_an_earthquake_JPM_Interest_Rate_Derivatives.pdf`

That reprocessed row was observed to have:

- `theme_count = 6`
- `trade_count = 5`
- non-null `document_hash = febd98a16e232cbb184419f9247d5d4774e24154a288df558773d7d698e4ffde`

The parser state DB also showed full success for that document:

- `parse_ok = 1`
- `boilerplate_ok = 1`
- `metadata_ok = 1`
- `themes_ok = 1`
- `trades_ok = 1`
- `storage_ok = 1`

Inference: the new code path is live and the dual-write path is active for newly processed documents.

## What `research_dispatcher` should assume today

For newly processed rows:

- `parsed_research.parsed_data` is still written and remains the archival source.
- `parsed_research.theme_count`, `trade_count`, and `document_hash` should be populated.
- `research_themes` and `research_theme_excerpts` should contain queryable normalized theme data.
- `research_theme_links` should currently be treated as empty / unavailable unless a future implementation starts populating it.

For legacy rows created before this rollout:

- `theme_count` may be `0`
- `trade_count` may be `0`
- `document_hash` may be `NULL`
- there may be no corresponding rows in `research_themes`

Because of that, `research_dispatcher` should currently use this read strategy:

1. Prefer normalized theme tables for rows that clearly went through the new path.
2. Fall back to `parsed_research.parsed_data` for legacy rows that have not been backfilled yet.

Practical gating signal for "new-path" rows:

- `document_hash IS NOT NULL`

Stronger signal if needed:

- `document_hash IS NOT NULL AND theme_count > 0`

## Suggested query approach for `research_dispatcher`

For normalized reads, join:

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`

Do not currently build production behavior around `research_theme_links`, because that table is not populated by either live writes or backfill.

Until backfill is complete, do not assume every `parsed_research` row has normalized children.

## Backfill status

There is no SQL backfill script yet.

The current backfill implementation is a Python script:

- [scripts/backfill_theme_normalization.py](/Users/ncdial/devwork/research_parser/scripts/backfill_theme_normalization.py)

There is also targeted test coverage for current normalization behavior:

- [tests/test_theme_normalization.py](/Users/ncdial/devwork/research_parser/tests/test_theme_normalization.py)

## Backfill caveats

The backfill script has been hardened since the initial rollout.

Current behavior:

- It replaces normalized theme rows per `research_id` rather than skipping rows that already have partial normalized data.
- Reruns clear and rebuild `research_themes` and `research_theme_excerpts` for the target document.
- It normalizes legacy `relevance` payloads so old records with string values like `"Rates"` can still be inserted into the `TEXT[]` column.

Initial production validation:

- `python scripts/backfill_theme_normalization.py --limit 50` completed successfully with:
  - `Processed: 50`
  - `Skipped: 0`
  - `Errors: 0`
- A mismatch check over the backfilled range returned effectively zero mismatches (`-0` from SQL formatting), meaning normalized theme counts matched `parsed_research.theme_count` for the checked rows.

Inference: the backfill script is now suitable for staged production rollout in batches, with validation between batches.

Even with the hardened script, `research_dispatcher` should still support mixed-mode reads until historical coverage is complete.

It should also avoid any dependency on `research_theme_links` until a separate link-resolution implementation ships.

## Not ready yet

The following should remain deferred:

- bulk production backfill using [scripts/backfill_theme_normalization.py](/Users/ncdial/devwork/research_parser/scripts/backfill_theme_normalization.py)
- applying [migrations/002_theme_constraints.sql](/Users/ncdial/devwork/research_parser/migrations/002_theme_constraints.sql)

## Recommended next engineering step

Before updating `research_dispatcher` to rely primarily on normalized tables for all history:

1. Continue staged backfill on historical rows.
2. Validate normalized counts against `parsed_data` after each batch.
3. Track remaining legacy rows where `document_hash IS NULL`.
4. Then move `research_dispatcher` fully onto normalized reads where appropriate.
