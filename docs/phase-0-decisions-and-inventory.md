# Phase 0 — decisions and compatibility inventory

Date: 2026-09-21  
Parent plan: [2026-09-20-suite-rationalization-plan.md](./2026-09-20-suite-rationalization-plan.md)  
Audit record: [suite-rationalization-review.md](/cursor/stores/bc-ebe34bae-392e-4466-aee6-b52fd753aa5e/docs/suite-rationalization-review.md)

This document records Phase 0 decisions for the Nexus-only execution track.
Production repointing on the Mac mini is **deferred**; repo changes assume the
mini as the eventual PostgreSQL host.

## Locked decisions (2026-09-21)

| # | Decision | Resolution |
| --- | --- | --- |
| Scope | Nexus-only code this week | No crontab/container repointing on the mini. Root `docker-compose.yml` and docs may assume the mini as eventual host. |
| Morning digest | Kill | Phase 1 for `morning_research` is remove/archive, not freeze-and-rebuild. |
| PostgreSQL host | Mac mini | Root-level `docker-compose.yml` provisions `nexus-postgres`. Not deployed from this agent run. |
| `research_pipeline_ops` | Not relevant | Do not bring into monorepo; not a blocker. Parser compose mount remains legacy until repoint. |
| Migration 004 claims | Settled (plan) | Drop parser `research_claims` / entities / relations. Analyst `argument_map` (`claim_key` / `referent_key`) is the one semantic store. |
| Re-derive vs backfill | Re-derive | Default path: clear `processed_files`, re-parse from Drive, re-run analyst. No dual-write or parity gates. |
| On-disk parser artifacts | Local re-generable cache | See [§ On-disk artifacts](#on-disk-artifacts). |
| Test baseline | Local suites + recorded results | See [internal/test-baseline-2026-09-21.md](/cursor/stores/bc-ebe34bae-392e-4466-aee6-b52fd753aa5e/internal/test-baseline-2026-09-21.md). No root CI workflow yet (judgment: defer until after Phase 2 port). |
| Slice 2/3 guardrails | Hard | No rewrite of prompts/linters/judge/rubric; relocate `tool_schema.json` before deleting `research-store`; `evals/eval.db` and golden JSONL stay SQLite. |

### Deferred (not blocking Nexus work)

| Item | Notes |
| --- | --- |
| Phase 0 decision 1 — deployment checkout | Repoint `research_processing/` crons/containers to Nexus. Relay is the worked example (PR #2). |
| Phase 0 decision 2 — corpus inventory | Document count and Drive integrity check can run at re-derive time; no cost estimate required before Phase 2. |
| Supabase export | Retain offline export until one full local parse → analyze → dispatch run (Phase 5 gate). |

## On-disk artifacts

Path: `RESEARCH_PARSER_ARTIFACT_BASE_DIR` (default `data/artifacts/{file_id}/`).

| File | Role |
| --- | --- |
| `document.md` | Normalized markdown from parser |
| `clean_text.md` | Boilerplate-stripped text; resume key |
| `blocks.jsonl`, `figures.jsonl`, `figures/` | Structured parse output |
| `parse.json` | Parse metadata (backend, confidence) |

**Disposition: local re-generable cache.**

- Not canonical after Phase 2 — PostgreSQL holds durable source and retrieval rows.
- Safe to delete for re-derive; parser rebuilds from Drive PDFs.
- Not absorbed into the database in Phase 2 (keeps parser resume/debug fast).
- Sunset: optional later if all consumers read from PostgreSQL only.

## Field ownership

One documented owner per durable semantic field crossing a package boundary.

| Field | Owner | Definition / storage | Consumers |
| --- | --- | --- | --- |
| `document_id` | **parser** | Drive file ID; `parsed_research.document_id` (migration 005) | analyst hydration (`parsed_db_client`), dispatcher parser mode (retiring) |
| `file_id` | **parser** (alias) | Same value as `document_id` in pipeline code | analyst `run_batch`, relay archive, morning_research (deleting) |
| `research_id` | **parser** | `parsed_research.id` surrogate PK | analyst, dispatcher ledger, store indexer (deleting) |
| `document_hash` | **parser** | Content hash of parsed document version | analyst `document_analysis` key, dispatch batch |
| `document_key` | **analyst** (canonical) | `file:{file_id}` or `doc:{research_id}:{document_hash}` | dispatch batch, pipeline_ops, parity validator |
| `parser_version` | **parser** | `parser-source-v1` (`research_memory/records.py`) | spans, artifacts, analyst `ParsedPayload` |
| `span_version` | **parser** | `span-v3` | `research_spans` |
| `chunker_version` (parser) | **parser** | `retrieval-chunker-v3` | `research_retrieval_chunks` |
| `chunker_version` (analyst) | **analyst** | `deterministic-theme-v1` (config) | **Different meaning** — analyst theme chunking, not parser retrieval |
| `analysis_version` | **analyst** | Default `argmap-v1` | `document_analysis`, dispatch batch, dispatcher |
| `claim_key` | **analyst** | `argument_map` payload | consensus, argument graph, street-agrees |
| `referent_key` | **analyst** | `argument_map` payload | evidence linking, graph queries |
| `batch_key` | **analyst** | Dispatch batch scope | dispatcher `AnalystBatchClient` |
| `street_agrees_splits` | **analyst** | Dispatch batch document field | dispatcher digest (`DIGEST_CONSENSUS_MODE`) |
| `DIGEST_CONSENSUS_MODE` | **analyst** (config) | Env `RESEARCH_ANALYST_DIGEST_CONSENSUS_MODE` | gates street-agrees in export + digest |
| Relay ledger key | **relay** | `gmail_msgid` or `proton:{Message-ID}` | archive job, delivery dedupe |

### Naming collisions (known)

1. **`file_id` ≡ `document_id`** — same Drive identifier, two names. Consolidate on `document_id` in new interfaces; keep `file_id` as a deprecated alias until Phase 4.
2. **`chunker_version`** — parser retrieval chunker vs analyst theme chunker. Never compare across packages without namespace.

## Legacy path sunset conditions

| Path | Sunset when |
| --- | --- |
| Supabase `parsed_research` writes (parser) | Phase 2 complete + re-derive verified |
| PostgREST reads (`parsed_db_client`, `calendar_db_client`) | Phase 3 PostgreSQL reads land |
| `research-store` / `distill_adapter` | **Done Phase 1** — schema relocated; adapter fails loudly |
| `morning_research` package | **Done Phase 1** — removed from Nexus; cron removal is ops ([checklist](./phase-1-ops-checklist.md)) |
| Dispatcher parser mode + `mark_as_synthesized` | Phase 4 defaults + deletion |
| Dispatcher Edge Functions / `report_feedback` | Phase 4 with `supabase/` deletion |
| JSON dispatch-batch file bridge | Optional post-Phase 3; not required for Supabase exit |
| On-disk `data/artifacts/` as implicit source | When all readers use PostgreSQL (post-Phase 2) |

## Supabase surface inventory

| Package | Client | Tables / surface | Phase disposition |
| --- | --- | --- | --- |
| `research_parser` | `supabase-py` | `parsed_research`, artifacts, spans, chunks | Port Phase 2 |
| `research_analyst` | PostgREST | parsed hydration, calendar, optional forecasts | Port Phase 3 |
| `research_dispatcher` | `supabase-py` | parser mode, `pipeline_ops` | Delete parser mode Phase 4; move ops schema |
| `research-store` | `supabase-py` | `parsed_research` index columns | Delete with package Phase 1 |
| `morning_research` | `supabase-py` | `research_digest_*` | Delete with package Phase 1 |
| `research-relay` | none | — | R1 metadata scrub (parallel track) |

## PostgreSQL connection (prepared, not wired)

Root compose service: `nexus-postgres` on port 5432.

Suggested URL for packages on the mini host:

```bash
NEXUS_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/nexus
```

From the parser container:

```bash
NEXUS_DATABASE_URL=postgresql://nexus:nexus@host.docker.internal:5432/nexus
```

Packages will adopt `NEXUS_DATABASE_URL` (or per-package `RESEARCH_*_DATABASE_URL` overrides) in Phases 2–3. Supabase vars remain until Phase 5.

## Next implementation slices (Nexus-only)

1. **R1** — relay attachment metadata scrubbing (fail-closed) — in progress
2. **Phase 1** — delete `morning_research`, delete `research-store` after `tool_schema.json` relocation
3. **Phase 2** — `SourceStore` + parser port + consolidated migrations
4. **Phase 3** — `AnalysisStore` repository seam + PostgreSQL consolidation
