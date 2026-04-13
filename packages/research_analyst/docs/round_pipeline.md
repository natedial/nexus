# Round-Based Agent Analysis Pipeline

## Architecture Overview

This document tracks the implementation of the debate-style multi-round agentic pipeline as defined in `docs/superpowers/plans/melodic-baking-bachman-v2.md`.

## Persistence Boundary Statement

**Supabase vs SQLite split:**
- `research_dispatcher` reads `parsed_research` from Supabase PostgreSQL (legacy path). It never writes back.
- `research_analyst` reads `parsed_research` from Supabase via `PARSED_DB_URL`/`PARSED_DB_KEY` and writes analysis results to a local SQLite file (`AnalysisStore`). It does **not** sync analysis results back to Supabase.
- The new `document_analysis` table lives in analyst SQLite only. Dispatcher consumes it **via the `AnalystBatchClient` JSON file bridge**, not via a Supabase sync.

## Research ID Audit

**Audit query:** `SELECT COUNT(*) FROM analysis_run_items WHERE research_id IS NULL AND status = 'success'`

**Result:** 0 (expected)

This confirms that all successful analysis runs have a non-null `research_id`, validating the `NOT NULL` constraint decision for the new `document_analysis` table.

## Baseline Metrics (to be populated during implementation)

- Token budget baseline: TBD
- Prompt cache hit rate baseline: TBD
- Orphan count: 0
- Cutover date: TBD

## Phase Progress

- [ ] Phase 0: Scaffolding
- [ ] Phase 1: Tool-enabled LLM client
- [ ] Phase 2: Round executor (dual-write)
- [ ] Phase 3: Batch export
- [ ] Phase 4: Dispatcher diff mode
- [ ] Phase 5: Cutover
- [ ] Phase 6: Cleanup
