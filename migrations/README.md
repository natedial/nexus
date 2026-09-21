# Consolidated schema migrations (Phase 2)

Nine SQL files currently live across four packages under three naming
conventions. Phase 2 will consolidate them into this directory with a single
ordering manifest.

## Carry forward

| Order | Source | Notes |
| --- | --- | --- |
| 1 | `packages/research_parser/migrations/001_theme_normalization_schema.sql` | Theme tables (if still needed post-prune) |
| 2 | `packages/research_parser/migrations/002_theme_constraints.sql` | |
| 3 | `packages/research_parser/migrations/003_parsed_research_document_identity.sql` | `document_id` identity |
| 4 | `packages/research_parser/migrations/005_parsed_research_document_id_identity.sql` | Canonical Drive `document_id` |
| 5 | `packages/research_parser/migrations/004_research_memory_substrate.sql` | **Partial** — spans, chunks, artifacts only; **drop** unused `research_claims` / entities / relations tables (parser 004 claims layer is retired; analyst `argument_map` is canonical) |
| 6 | `packages/research_analyst/migrations/001_agent_tables.sql` | Agent run tables → PostgreSQL in Phase 3 |
| 7 | `packages/research_dispatcher/supabase/migrations/20260402105000_create_pipeline_ops.sql` | Move `pipeline_ops` schema out of `supabase/` |

## Drop (do not port)

| Source | Reason |
| --- | --- |
| `packages/research_dispatcher/supabase/migrations/001_create_report_feedback.sql` | Retired Edge Function surface |
| `packages/morning_research/migrations/001_research_digest.sql` | Package killed (Phase 1) |
| Parser 004 `research_claims` / entity / relation tables | Second semantic store; analyst maps are canonical |

## Runner

No migration runner exists today. Phase 2 will add a plain ordered manifest
(for example `apply.sh` or a numbered `NNN_*.sql` sequence). Until then this
directory documents intent only.
