# Round-Based Agent Analysis Pipeline

## Related Documents

- **Design:** [melodic-baking-bachman-v2.md](/Users/ncdial/devwork/research_processing/docs/superpowers/plans/melodic-baking-bachman-v2.md)
- **Review:** [melodic-baking-bachman-v2-review.md](/Users/ncdial/devwork/research_processing/docs/superpowers/plans/melodic-baking-bachman-v2-review.md)
- **Remediation Punchlist:** [melodic-baking-bachman-v2-review-punchlist.md](/Users/ncdial/devwork/research_processing/docs/superpowers/plans/melodic-baking-bachman-v2-review-punchlist.md)

## Architecture Overview

This document tracks the implementation of the debate-style multi-round agentic pipeline as defined in `docs/superpowers/plans/melodic-baking-bachman-v2.md`.

## Persistence Boundary Statement

**Supabase vs SQLite split:**
- `research_dispatcher` reads `parsed_research` from Supabase PostgreSQL (legacy path). It never writes back.
- `research_analyst` reads `parsed_research` from Supabase via `RESEARCH_ANALYST_PARSED_DB_URL`/`RESEARCH_ANALYST_PARSED_DB_KEY` (defaulting to the shared `SUPABASE_URL`/`SUPABASE_KEY`) and writes analysis results to a local SQLite file (`AnalysisStore`). It does **not** sync analysis results back to Supabase.
- The new `document_analysis` table lives in analyst SQLite only. Dispatcher consumes it **via the `AnalystBatchClient` JSON file bridge**, not via a Supabase sync.

## Research ID Audit

**Audit query:** `SELECT COUNT(*) FROM analysis_run_items WHERE research_id IS NULL AND status = 'success'`

**Result:** 0 (expected)

This confirms that all successful analysis runs have a non-null `research_id`, validating the `NOT NULL` constraint decision for the new `document_analysis` table.

## Baseline Metrics (Post-Migration)

- Token budget baseline: TBD (measure after running rounds mode)
- Prompt cache hit rate baseline: TBD (measure after running rounds mode)
- Orphan count: 0
- Cutover status: **IN PROGRESS** - see punchlist for details

## Migration Notes (Completed 2026-04-13)

### Changes Made in Phase 6:
- Dropped legacy tables: `trading_analysis`, `short_time_horizon_analysis`, `talking_points_analysis`
- Removed deprecated wrapper classes: `TradingAnalysis`, `ShortTimeHorizonAnalysis`, `TalkingPointsAnalysis`
- Removed legacy `AgentExecutor` - now uses `RoundExecutor` only
- Removed diff mode from dispatcher
- Default `RESEARCH_ANALYST_ROUND_MODE` is now `rounds`

### Removed Files:
- `src/research_analysis_layer/services/agent_executor.py` (legacy executor)
- `src/dispatch_batch_differ.py` (diff comparison)
- `tests/test_dispatch_batch_differ.py` (diff tests)

## Current Status (per punchlist)

The following items have been addressed:
- R1: Gate round execution safely - RoundExecutor now requires valid LLM client
- R2: Repair document_analysis write contract - Fixed store call with explicit fields
- R3: Rewire tool use end to end - Tool registry injected, full schemas passed
- R4: Preserve stable dispatcher evidence substrate - Added evidence fields to payload
- R5: Fix batch export live-row behavior - Fixed row access, added latest-per-document logic
- R7: Offline parity-validation harness - Created `parity_validator.py` with CLI
- R8: Correct rollout documentation - This document updated

Blocked items:
- R6: Validate dispatcher ingestion - Requires dispatcher-side work

## Cutover Guard Queries

The offline parity validation harness is now available:
```bash
python -m research_analysis_layer.services.parity_validator \
    --store path/to/analysis.db \
    --legacy path/to/legacy_documents.json \
    --date-from 2026-04-01 \
    --date-to 2026-04-07
```

Before Phase 5/6 advance, validation must confirm:
1. Repaired analyst batch export produces same core evidence fields as legacy path
2. Dispatcher can ingest the new batch format without manual massaging (R6)
3. Document count and date span meet minimum thresholds

See punchlist item R7 for detailed requirements.

## Phase Progress

- [x] Phase 0: Scaffolding
- [x] Phase 1: Tool-enabled LLM client
- [x] Phase 2: Round executor (dual-write)
- [x] Phase 3: Batch export
- [x] Phase 4: Dispatcher diff mode
- [ ] Phase 5: Cutover (BLOCKED - parity validation required, see R7)
- [ ] Phase 6: Cleanup (BLOCKED - awaiting R7 completion)
