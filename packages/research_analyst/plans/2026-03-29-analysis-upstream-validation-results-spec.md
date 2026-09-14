# Analysis Upstream Validation Results Spec

Last updated: 2026-03-29 America/New_York

## Goal

Record what was actually validated about the upstream parser systems and translate those findings into an implementation-ready contract for the analysis layer.

This document is based on:

- live inspection of the parser SQLite `state.db`
- live read-only Supabase queries against parser-owned tables
- parser application code
- parser migration files

It replaces several March 27 assumptions with verified current behavior.

## Validation coverage

Validated directly:

- local `state.db` path and schema
- live `processed_files` row shape and current status distribution
- live Supabase access path
- live existence and sample field sets for `parsed_research`
- live existence and sample field sets for `research_themes`
- live existence and sample field sets for `research_theme_excerpts`
- live existence and current emptiness of `research_theme_links`
- live document-to-theme-to-excerpt hydration path for one recent document

Validated by code inspection:

- how parser state transitions are written
- how parsed document rows are inserted or updated
- how `document_hash` is computed
- how normalized theme and excerpt rows are written
- how parser metadata carries the Google Drive file id

Not fully validated:

- broad 20 to 30 document corpus quality review
- cross-version behavior from a live rerun of the same source file
- SQL-level constraints in the current remote Supabase instance beyond fields observable through the API

## Verified upstream systems

## `state.db`

Current live path in `research_parser`:

- `../research_parser/data/state.db`

Current live table:

- `processed_files`

Live schema:

- `file_id TEXT PRIMARY KEY`
- `file_name TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'pending'`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `parse_ok INTEGER`
- `boilerplate_ok INTEGER`
- `metadata_ok INTEGER`
- `themes_ok INTEGER`
- `trades_ok INTEGER`
- `storage_ok INTEGER`
- `error_message TEXT`

Observed live status counts on 2026-03-29:

- `completed`: 600
- `failed`: 8

Observed semantics from code and live rows:

- success is represented by `status = 'completed'`
- successful rows also show `storage_ok = 1` in the observed sample
- the only usable watermark currently exposed is `updated_at`
- `state.db` tracks file-level processing, not parsed document ids

Fields not present in `state.db`:

- `research_id`
- `document_hash`
- explicit `completed_at`

## Parsed database

Current live access method:

- Supabase PostgreSQL via the parser repo's configured `SUPABASE_URL` and `SUPABASE_KEY`

Live tables confirmed via read-only queries:

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`
- `research_theme_links`

Observed live row counts on 2026-03-29:

- `parsed_research`: 801
- `research_themes`: 6471
- `research_theme_excerpts`: 12092
- `research_theme_links`: 0

### `parsed_research`

Observed live fields:

- `id`
- `document_name`
- `source`
- `source_date`
- `parsed_data`
- `parsed_at`
- `synthesized`
- `synthesized_batch_id`
- `index_status`
- `indexed_at`
- `index_error`
- `indexing_batch_id`
- `index_version`
- `index_attempts`
- `document_title`
- `publisher`
- `area`
- `region`
- `asset_focus`
- `document_link`
- `theme_count`
- `trade_count`
- `document_hash`

Observed `parsed_data` top-level keys in a live sample:

- `themes`
- `trades`
- `metadata`
- `full_text`
- `extraction_stats`

Implication:

- raw content fallback is available today as `parsed_data.full_text`

### `research_themes`

Observed live fields:

- `id`
- `research_id`
- `theme_order`
- `label`
- `scope`
- `primary_category`
- `relevance`
- `classification`
- `strength`
- `confidence`
- `evidence_count`
- `mention_count`
- `context`
- `directionality`
- `argument_structure`
- `created_at`

### `research_theme_excerpts`

Observed live fields:

- `id`
- `theme_id`
- `excerpt_order`
- `excerpt_text`
- `created_at`

Implication:

- excerpt ordering is available
- page spans, paragraph offsets, and source spans are not available in the normalized excerpt table

### `research_theme_links`

Current live state:

- table exists
- row count is `0`

Implication:

- the analysis layer should not depend on parser-owned theme-link rows in v1

## Verified hydration path

The current real join path is:

1. select candidate file rows from `state.db.processed_files`
2. use `file_id` as the bridge key into parsed content
3. match `file_id` to `parsed_research.parsed_data.metadata.document_id`
4. read the parsed document row from `parsed_research`
5. join `parsed_research.id` to `research_themes.research_id`
6. join `research_themes.id` to `research_theme_excerpts.theme_id`

Additional bridge field:

- `parsed_research.document_link` also embeds the same Google Drive file id

Verified sample:

- live `state.db` latest row used `file_id = 1g2sjyhE7Is08a890bjftVZVDX4CXjU5f`
- matching live parsed row exposed `parsed_data.metadata.document_id = 1g2sjyhE7Is08a890bjftVZVDX4CXjU5f`

## Contract mismatches versus the March 27 target

## Mismatch 1: `state.db` is not keyed by `research_id`

Original assumption:

- the analysis layer could select parser-success documents directly by `research_id`

Verified reality:

- `state.db` only tracks `file_id` and file-level step state
- `research_id` exists only in the parsed database

Required adaptation:

- selection begins from `file_id`
- hydration must bridge from `file_id` into `parsed_research`

## Mismatch 2: no explicit parser `completed_at`

Original assumption:

- `completed_at` would be available as a stable selection watermark

Verified reality:

- only `updated_at` is available in `processed_files`

Required adaptation:

- use `updated_at` as the current watermark
- treat it as a file-state timestamp rather than a dedicated storage-complete timestamp

## Mismatch 3: `document_hash` is not available in `state.db`

Original assumption:

- `document_hash` would be available directly at selection time

Verified reality:

- `document_hash` exists on `parsed_research`, not in `state.db`

Required adaptation:

- fetch the parsed document row before duplicate/version checks keyed by `document_hash`

## Mismatch 4: `research_id` stability differs from the earlier assumption

Original assumption:

- `research_id` might be a stable document identity across changed versions

Verified reality from parser code:

- parser lookup reuses an existing `parsed_research.id` only when the tuple of `document_hash`, `document_name`, and `source` already exists
- if `document_hash` changes, the parser is likely to insert a new document row

Inference:

- current `research_id` should be treated as a parsed-row identifier, not a stable cross-version document id

## Recommended current upstream contract

The analysis layer should use this verified contract for bootstrap work.

### Selection contract

- read from `state.db.processed_files`
- candidate success condition: `status = 'completed'`
- strongly prefer also requiring `storage_ok = 1`
- use `updated_at` as the selection watermark
- treat `file_id` as the upstream bridge key

### Parsed document contract

Hydrate documents from `parsed_research` and expect at least:

- `id`
- `document_name`
- `source`
- `source_date`
- `document_hash`
- `theme_count`
- `document_link`
- `parsed_data`

Strongly preferred normalized fields already present:

- `document_title`
- `publisher`
- `area`
- `region`
- `asset_focus`

### Theme contract

Hydrate themes from `research_themes` and expect:

- `id`
- `research_id`
- `theme_order`
- `label`
- `relevance`
- `classification`
- `strength`
- `confidence`
- `context`
- `directionality`
- `argument_structure`

### Excerpt contract

Hydrate excerpts from `research_theme_excerpts` and expect:

- `theme_id`
- `excerpt_order`
- `excerpt_text`

### Raw content contract

For v1 fallback chunking or inspection:

- use `parsed_research.parsed_data.full_text`

## Data quality notes

Observed in the latest live sample:

- `theme_count` matched the actual number of child `research_themes` rows
- excerpt ordering was present
- document metadata included `document_id`, `document_uri`, and `document_link`
- filename and extracted `source` may diverge, so source-metadata coherence should be treated as a real validation rule during ingestion

## Recommended doc updates from this validation

Update the March 27 contract and bootstrap docs to reflect:

- `file_id`, not `research_id`, is the initial selection key
- `updated_at`, not `completed_at`, is the current parser watermark
- the join into parsed content is through `parsed_data.metadata.document_id`
- `research_id` should be treated as a parsed-row id, not a stable cross-version identity
- `research_theme_links` exists but is not populated, so it is non-essential for v1

## Exact commands used

Local SQLite inspection:

```bash
sqlite3 ../research_parser/data/state.db ".schema processed_files"
sqlite3 -header -column ../research_parser/data/state.db \
  "SELECT status, COUNT(*) AS count FROM processed_files GROUP BY status ORDER BY status;"
sqlite3 -header -column ../research_parser/data/state.db \
  "SELECT file_id, file_name, status, parse_ok, boilerplate_ok, metadata_ok, themes_ok, trades_ok, storage_ok, created_at, updated_at FROM processed_files ORDER BY updated_at DESC LIMIT 10;"
sqlite3 -header -column ../research_parser/data/state.db \
  "SELECT file_id, file_name, status, error_message FROM processed_files WHERE status IN ('failed','partial') ORDER BY updated_at DESC LIMIT 10;"
```

Parser code and migration inspection:

```bash
sed -n '1,260p' ../research_parser/src/storage/state.py
sed -n '1,280p' ../research_parser/src/storage/supabase.py
sed -n '300,460p' ../research_parser/src/pipeline.py
sed -n '1,220p' ../research_parser/migrations/001_theme_normalization_schema.sql
```

Live Supabase validation:

```bash
PYTHONPATH=. .venv/bin/python scripts/test_supabase.py
PYTHONPATH=. .venv/bin/python -c "<read-only table count and field inspection>"
PYTHONPATH=. .venv/bin/python -c "<read-only document/theme/excerpt sample inspection>"
PYTHONPATH=. .venv/bin/python -c "<read-only join-key inspection via parsed_data.metadata.document_id>"
```

## Acceptance criteria

This validation result is sufficient when:

- the next coding agent can build adapters around the real upstream shape
- the major mismatches from the March 27 target are explicit
- the initial bootstrap implementation no longer needs to invent selection keys or join paths

## Related documents

- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)
- [2026-03-27-upstream-integration-contract-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-upstream-integration-contract-spec.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-29-analysis-planning-round-closeout-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-planning-round-closeout-plan.md)

## Status

`VALIDATED_WITH_LIVE_UPSTREAM_EVIDENCE`
