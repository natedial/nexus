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
| 6b | `migrations/002_analyst_schema.sql` | **Applied in Phase 3** — analyst semantic layer + Slice 2 consensus tables |
| 7 | `migrations/003_pipeline_ops_schema.sql` | **Applied in Phase 4** — `pipeline_ops` schema |
| 8 | `migrations/004_supply_events.sql` | **Applied in Phase 4** — supply calendar table for dispatcher |

## Drop (do not port)

| Source | Reason |
| --- | --- |
| `packages/research_dispatcher/supabase/migrations/001_create_report_feedback.sql` | Retired Edge Function surface |
| `packages/morning_research/migrations/001_research_digest.sql` | Package killed (Phase 1) |
| Parser 004 `research_claims` / entity / relation tables | Second semantic store; analyst maps are canonical |

## Runner

Apply parser schema migrations:

```bash
docker compose up -d postgres
./migrations/apply.sh
```

Uses `RESEARCH_PARSER_DATABASE_URL` or `NEXUS_DATABASE_URL` (default
`postgresql://nexus:nexus@localhost:5432/nexus`).

| File | Status |
| --- | --- |
| `001_parser_schema.sql` | **Applied in Phase 2** — parser tables without 004 claims/entities/relations |
| `002_analyst_schema.sql` | **Applied in Phase 3** — analyst tables, consensus/shadow tables, agent tables |
| `003_pipeline_ops_schema.sql` | **Applied in Phase 4** — pipeline_ops schema |
| `004_supply_events.sql` | **Applied in Phase 4** — supply calendar events |
