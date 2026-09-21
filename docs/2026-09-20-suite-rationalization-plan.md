# Research suite rationalization plan

Date: 2026-09-20
Revised: 2026-09-20 — v3, after Slice 2/3 consensus and eval work landed on Nexus `main` (PRs #4–#7, #9–#13). v2 was the code-audit correction of all six packages.

## Objective

Reduce Nexus to one coherent research workflow:

```text
research-relay or direct source intake
    -> research_parser
    -> canonical source and retrieval records
    -> research_analyst
    -> canonical claims, entities, relations, and forecasts
    -> research_dispatcher / morning digest / query clients
```

Those canonical claims are the analyst `argument_map` (`claim_key` /
`referent_key`), not parser migration 004 tables. Consensus, the argument
graph, and street-agrees are derived from the maps. Parser 004 is dropped
(Phase 0 decision 4).

The `research-relay -> research_parser` edge does not exist yet. Relay archives
to Drive folders and the parser independently polls Drive; nothing hands off.
Building that edge is tracked below as R2.

### Settled after Slice 2/3 (sequencing rules, not open questions)

These are locked. Later phases port persistence around them; they do not
re-litigate or rewrite the shipped consensus/eval surface.

1. **Canonical claims are analyst maps.** `argument_map` (`claim_key` /
   `referent_key`) is the one semantic store. Consensus, the argument graph, and
   street-agrees are derived from those maps. Parser migration 004 is dropped
   (Phase 0 decision 4). Phase 2's consolidated schema must not recreate 004's
   claims/entities/relations tables.
2. **Do not rewrite shipped Slice 2/3.** Protect the live prompts
   (`contrarian.md`, `challenger.md`, `argument_graph_guide.md`), the eval
   surface (`lint_argument_map`, `lint_consensus_divergence`, `ArgumentJudge`,
   rubric metrics/gate, golden rubric report), and `DIGEST_CONSENSUS_MODE`.
   Positions remain publisher identities, never thesis/contrarian/positioning
   lenses. Promotion-gate floors and `ARGUMENT_JUDGE_WEIGHT_*` stay config, not
   hard-coded constants or Postgres columns.
3. **Deleting `research-store` must relocate `tool_schema.json` first.**
   `ToolRegistry` boots from that file. The Slice 2 `argument_graph` tool is
   analyst-local and already registers in-process; `research_search` still
   depends on the store schema until it is moved.
4. **The `AnalysisStore` split is larger, not different.** Slice 2 added
   `consensus_cluster_state`, `consensus_shift_events`, and
   `shadow_street_digest`. Consensus/divergence *points* stay queries over
   maps. Golden JSONL and `evals/eval.db` stay SQLite; do not port linters,
   the judge, or the rubric report onto PostgreSQL.
5. **Checkout mismatch is unchanged.** Production except relay still runs from
   `research_processing/`. There is still no analyst crontab. Dispatcher
   reconcile must take Nexus `DIGEST_CONSENSUS_MODE` (PR #6) and later
   digest/eval landings, not only `cursor/slice2-street-digest-a21e`.

## Driver

Exit Supabase to remove hosted-service cost and coupling during development.

The suite is pre-production: no external consumers, no SLA, and no production
history to protect. Every other decision in this plan follows from those two
facts, and two consequences shape the whole document:

1. **The Supabase exit is the spine.** Five packages hold a Supabase client
   today. Sequencing is driven by how much Supabase surface each step removes.
2. **Pre-production removes the migration ceremony.** Dual-write, shadow reads,
   parity windows, and "one full operational cycle with no consumers" exist to
   protect production consumers. There are none. They are replaced by a single
   retained export and a re-derivation path.

## Current state, verified 2026-09-20

The first version of this plan assumed several things that the code contradicts.
Corrected before planning against them:

| v1 assumption | Reality |
|---|---|
| Supabase is not required for the current phase | Required by the parser (writes), the analyst (reads), the dispatcher (parser mode), and research-store (indexer) |
| SQLite holds operational state only | The analyst's entire semantic layer, the dispatcher ledger, the research-store corpus, and the eval database are all SQLite |
| Repository interfaces exist to put adapters behind | None exist. `AnalysisStore` is a single ~2,688-line class with embedded DDL |
| Relay feeds the parser | No such edge in code |
| `morning_research` parses PDFs | It downloads them; Codex reads them. There is no Python parser |
| The dispatcher writes `parsed_research.synthesized` as primary state | Already gated behind `LEGACY_SYNTHESIZED_UPDATES` and skipped entirely in analyst mode |

### What is actually running, and from where

Verified 2026-09-20 against `crontab`, `launchctl`, and `docker inspect`. **Every
production service except relay runs from the legacy
`/Users/ncdial/devwork/research_processing/` checkout, not from this monorepo.**

| Service | How it runs | Source checkout |
|---|---|---|
| `research_parser` | Docker container `research-parser`, up and healthy | `research_processing/research_parser` |
| `research-store` indexer | Docker container `research-store-indexer-1`, up ~3 weeks | `research_processing/research-store` |
| `research_dispatcher` | cron, Sun and Wed 23:00, `MODE=production` | `research_processing/research_dispatcher`, on branch `cursor/slice2-street-digest-a21e` |
| `morning_research` | cron, Sun–Fri 06:10 | `research_processing/morning_research`, on branch `cursor/author-argument-prompt-split` |
| `research-relay` | LaunchAgents `com.researchrelay.email` (300s) and `com.researchrelay.archive` (8h) | `nexus/packages/research-relay` — repointed by PR #2 |
| `research_analyst` | no schedule found; run by hand | Nexus `packages/research_analyst` holds Slice 2/3 (`DIGEST_CONSENSUS_MODE`, argument graph, evals). That code is not live until someone runs this checkout. |

This is the single largest execution risk in the plan, and it has three parts:

1. **Changes made in this monorepo do not reach production.** The entire
   migration could be completed here while the live pipeline keeps running the
   old code against Supabase. That includes today's Slice 2/3 analyst work:
   there is still no analyst cron, so none of it is live.
2. **Two production services run unmerged feature branches**, and the legacy
   dispatcher checkout also has uncommitted changes and untracked files. Legacy
   production code is not a subset of what is in this repository — repointing
   could silently drop behavior. The dispatcher branch is an older street-digest
   cut. When reconciling it, take Nexus `DIGEST_CONSENSUS_MODE` (PR #6) and the
   later digest/eval landings, not only `cursor/slice2-street-digest-a21e`.
3. **The dispatcher cron passes deprecated unprefixed variables**
   (`MODE=production`, `USE_SKILL_PIPELINE=true`). Per `docs/environment.md`
   these are fallbacks for the `RESEARCH_DISPATCHER_*` names. When the fallbacks
   are removed, the cron silently reverts to defaults — `MODE` defaults to
   `debug` — rather than failing.

Reconciling this is Phase 0 decision 1 below. Relay is the worked example: PR #2
repointed its LaunchAgents at the Nexus checkout, and the same needs doing for
everything else.

### Supabase surface to remove

| Package | Surface | Disposition |
|---|---|---|
| `research_parser` | `supabase-py`; writes `parsed_research`, `research_document_artifacts`, `research_spans`, `research_retrieval_chunks` | Port |
| `research_analyst` | Raw PostgREST reads in `db/parsed_db_client.py` and `db/calendar_db_client.py`; optional `economic_event_forecasts` write | Port |
| `research_dispatcher` | `supabase-py` parser-mode queries; `pipeline_ops` schema; Edge Functions and Storage (retired) | Delete parser mode; delete the retired function surface |
| `research-store` | `distill-index-supabase` worker over `parsed_research` | Delete with the package |
| `morning_research` | Optional `research_digest_*` tables | Delete with the package |

The dispatcher also carries non-Postgres Supabase surface — Edge Functions and
Storage — that a local PostgreSQL would not replace. **It has been retired and
is no longer in use, so it is deleted rather than ported.** The surface is
entirely self-contained:

- `supabase/functions/feedback/index.ts` is the only writer of `report_feedback`;
  no Python reads that table
- `supabase/functions/document/index.ts` and
  `supabase/storage/document-viewer.html` back the hosted document viewer
- `supabase/migrations/001_create_report_feedback.sql` therefore does not carry
  forward, leaving eight migrations to consolidate rather than nine
- the only Python involved is feedback and viewer link injection at
  `src/pdf_generator.py:366-393`, gated behind `FEEDBACK_ENABLED` (default
  `false`), plus the four `FEEDBACK_*` / `DOCUMENT_*` settings in `config.py` and
  their validation, and the cases in `tests/test_pdf_generator.py:58-69`

Deleting all of it removes `packages/research_dispatcher/supabase/` wholesale
once `20260402105000_create_pipeline_ops.sql` moves out, and takes the hardcoded
project URL default at `config.py:143` and the committed CLI cache at
`supabase/.temp/` (which contains `project-ref` and `pooler-url`) with it.

## Database strategy

One local PostgreSQL instance is the canonical research database. SQLite is
reserved for genuinely local operational state.

### PostgreSQL owns

- source documents and parser artifact metadata
- spans and retrieval chunks
- claims, evidence, entities, relations, and forecasts — meaning analyst
  `argument_map` / graph / consensus-shift state, not parser migration 004
- pipeline operations and run history
- dispatch history and durable semantic records

### SQLite owns

- parser polling state (`processed_files`)
- relay delivery and archive ledgers
- the analyst eval database and golden files (`evals/eval.db`, `evals/golden/`)
- local locks, retry queues, tests, fixtures, and temporary caches

Note the size of the gap: today SQLite holds far more than this list, and
closing that gap is most of Phase 3.

Supabase remains a possible future deployment target, not a current
requirement. New code uses portable PostgreSQL and package-owned repository
interfaces rather than provider-specific behavior.

### Migration method: re-derive, do not backfill

There is no production history to preserve, so rebuilding the corpus is cheaper
than migrating it:

1. Stand up local PostgreSQL and apply the consolidated schema.
2. Clear the parser's `processed_files` watermark and let it re-parse from the
   Drive source folder into the new database.
3. Re-run the analyst over the re-parsed corpus.

This removes the entire backfill, dual-write, hash-comparison, and parity-gate
workstream that v1 specified. It has one cost — the LLM spend of re-running the
analyst across the corpus — and one prerequisite: the Drive source documents
must be intact. Both are checked in Phase 0. Fall back to a one-time table
export only if that spend is unacceptable.

Retain a full export of the Supabase project until the local stack has completed
one end-to-end run. That is the rollback, and for a pre-production system it is
sufficient.

### Schema consolidation

Nine SQL migrations live in four packages under three naming conventions:

- `packages/research_parser/migrations/001..005`
- `packages/research_analyst/migrations/001_agent_tables.sql`
- `packages/research_dispatcher/supabase/migrations/001_create_report_feedback.sql` and `20260402105000_create_pipeline_ops.sql`
- `packages/morning_research/migrations/001_research_digest.sql`

There is no migration runner. Standing up local PostgreSQL includes choosing one
— plain SQL files with an ordering manifest is enough at this stage — and
deciding which carry forward. Three are already settled:
`001_create_report_feedback.sql` is dropped with the retired function surface,
`20260402105000_create_pipeline_ops.sql` moves out of the `supabase/`
directory, and parser migration 004's claims/entities/relations tables are
**dropped, not adopted**. No live code writes them. The live claims layer is
analyst-owned: `argument_map` with `claim_key` / `referent_key`, plus consensus,
the argument graph, and street-agrees derived from those maps. Adopting 004 as
canonical would create the second semantic store the non-goals forbid.

### Where the instance lives

`packages/research_parser/docker-compose.yml` is written for a containerized
deployment with Raspberry Pi memory limits, and it mounts
`../research_pipeline_ops` from outside the monorepo. "One local PostgreSQL"
therefore needs a designated host and a reachable address, not a localhost
socket, unless every package runs on the same machine. Settle this in Phase 0.

`AGENTS.md` states the repo root is not an app. A shared development database is
infrastructure rather than an app, so a root-level compose file defining only the
`postgres` service is the intended exception. Each package keeps its own
install/run/test commands and connects by URL.

## Protected core, restated honestly

v1 promised the parser and analyst were protected and then required moving
analyst semantic state to PostgreSQL. Both cannot be true. The honest boundary:

- **Protected:** parser extraction logic; analyst reasoning; agent prompts
  (including the Slice 2/3 `contrarian.md`, `challenger.md`, and
  `argument_graph_guide.md` additions); the domain models of both packages
  (positions are publishers only); and the Slice 3 eval surface
  (`lint_argument_map`, `lint_consensus_divergence`, `ArgumentJudge`, rubric
  metrics/gate, golden rubric report). Port persistence around these. Do not
  rewrite them as part of this migration. Calibration knobs
  (`PROMOTION_GATE_*`, `ARGUMENT_JUDGE_WEIGHT_*`) stay env config.
- **In scope:** their persistence adapters. The analyst's persistence layer has
  to change, because the Supabase exit and the one-semantic-store goal both
  require it.

Schema additions to the canonical source layer remain additive, and each must be
justified by a downstream query or provenance requirement.

## Target package disposition

| Package | Target disposition | Scope of work |
|---|---|---|
| `research_parser` | Protected core | Preserve extraction logic and models. Port persistence to PostgreSQL behind a `SourceStore` interface. Add a second intake adapter for relay. |
| `research_analyst` | Protected core, persistence in scope | Preserve reasoning, prompts, argument maps, and evals. Extract a repository seam from `AnalysisStore`, port PostgREST reads, and consolidate the semantic layer into PostgreSQL. Consensus/divergence points stay queries over maps, not a second store. |
| `research-relay` | Retain as transport boundary | Keep independent of analysis. Complete attachment metadata sanitization, then build the intake handoff. |
| `research_dispatcher` | Retain, narrow | Keep editorial synthesis, rendering, delivery, and dispatch history. Remove parser mode and the retired feedback surface, which together remove its Supabase client. |
| `research-store` | Delete | Verify the distill tool is actually dead. Relocate `tool_schema.json` (or an analyst-local copy) so `ToolRegistry` still boots. Preserve ranking logic and eval queries in the canonical retrieval module, then remove the package. |
| `morning_research` | Prune, then archive | Delete the Drive/Codex/Supabase path now. Keep Notion publishing as a library only if the digest survives. |

## Non-goals

- Do not rewrite parser extraction or analyst reasoning, prompts, or Slice 3
  evals as part of this work.
- Do not treat positions as thesis, contrarian, or positioning lenses; they
  are publisher identities only.
- Do not hard-code promotion-gate floors or argument-judge weights; those stay
  in `RESEARCH_ANALYST_*` config.
- Do not merge all packages into one Python distribution.
- Do not make relay responsible for analysis or persistence.
- Do not preserve multiple semantic stores for the same document version.
  Do not adopt parser migration 004 as a second claims store.
- Do not build backfill, dual-write, or parity tooling for a pre-production
  system.
- Do not port any Supabase surface that is already scheduled for deletion.

## Phase 0 — decisions and inventory

Six blocking decisions, all of which later phases depend on. The first is the
prerequisite for every other phase. Decision 4 is now settled (drop parser 004;
keep claims analyst-owned). The rest are still cheap to answer.

1. **Reconcile the deployment checkout.** Production runs from
   `research_processing/`, not from here. For each of parser, research-store
   indexer, dispatcher, and `morning_research`: diff the running branch against
   this repository, land anything missing, then repoint the cron entry or
   container at the Nexus checkout — as PR #2 already did for relay. Until this
   is done, no phase below has any production effect. While repointing the
   dispatcher, replace the deprecated unprefixed `MODE` and `USE_SKILL_PIPELINE`
   cron variables with their `RESEARCH_DISPATCHER_*` equivalents, and take the
   Nexus street-agrees path gated by `DIGEST_CONSENSUS_MODE` rather than only
   the older `cursor/slice2-street-digest-a21e` branch. The analyst still has
   no crontab; Slice 2/3 on Nexus `main` has no production effect until this
   checkout is what gets run.
2. **Re-derive or export?** Count documents in `parsed_research`, estimate the
   analyst re-run cost, and confirm the Drive sources are intact. Default:
   re-derive.
3. **PostgreSQL host.** One machine for everything, or a reachable instance
   shared across hosts? Note that the parser runs as a container today, so this
   is not automatically a localhost socket.
4. **Migration 004 tables — settled.** Drop them. Keep claims, evidence keys,
   consensus, and the argument graph analyst-owned on `argument_map`. Do not
   adopt parser 004 as a second canonical claims store.
5. **On-disk parser artifacts.** `data/artifacts/{file_id}/` holds
   `document.md`, `clean_text.md`, `blocks.jsonl`, `figures.jsonl`, and
   `parse.json`. Canonical, cache, or absorbed into the database?
6. **`research_pipeline_ops`.** Bring it into the monorepo or pin it as a
   declared external dependency. Three packages import it, it is not here, and
   the legacy checkout has its own copy at
   `research_processing/research_pipeline_ops`.

The Edge Functions and Storage surface was a further decision in an earlier
draft. It is settled: that surface is retired and is deleted, not replaced.

Alongside the decisions, build the compatibility inventory — but scope it to
fields that actually cross a package boundary today: `document_id`,
`research_id`, `document_hash`, `document_key`, the parser version constants
(`parser-source-v1`, `span-v3`, `retrieval-chunker-v3`), `analysis_version`, the
`DispatchBatch` fields (including `street_agrees_splits`), `claim_key`,
`referent_key`, `DIGEST_CONSENSUS_MODE`, and the relay ledger keys.

Record the two known naming collisions: `file_id` and `document_id` are the same
Drive identifier under two names, and the analyst's `chunker_version` shares a
name with the parser's while meaning something different.

Acceptance criteria:

- one documented owner for every durable semantic field
- every legacy path has an explicit sunset condition
- the remaining open Phase 0 decisions (1, 2, 3, 5, 6) are written down;
  decision 4 is settled as analyst-owned maps

## Phase 1 — shrink the Supabase surface by pruning

Pruning first is not tidiness. Each package removed here is one fewer Supabase
client to port in Phases 2 and 3.

This phase does not modify parser extraction or analyst reasoning. Deleting
`research-store` is the settled exception that *must* touch a thin analyst boot
path (see constraint 3 above):
`ToolRegistry` loads schemas from
`packages/research-store/distill_tool/tool_schema.json` and fails if that file
is gone. Relocate or stub that schema (and `distill_adapter`) as part of
deleting the package. Do not treat "no analyst code changes" as license to
delete the store first.

### `morning_research`

Nothing in the repo imports this package, but **it is live**: a cron entry runs
`research_processing/morning_research/schedule/run_daily.sh` Sunday through
Friday at 06:10, from the legacy checkout on branch
`cursor/author-argument-prompt-split`. An earlier draft of this plan called it
dormant on the strength of the example LaunchAgent in `schedule/`; that was
wrong, and the freeze is a decommission of a running job rather than a
formality.

1. Decide whether the morning digest is still wanted at all. If not, this whole
   section collapses to removing the cron entry and deleting the package.
2. Remove the cron entry, or repoint it at Nexus first if the digest must keep
   running during the migration.
3. Freeze feature work. Drop `drive_pull.py` and `codex_runner.py`.
4. Delete `supabase_store.py` and `migrations/001_research_digest.sql`. That is
   an entire Supabase client removed rather than ported.
5. Keep `notion_client.py`, `markdown_blocks.py`, and `qc.py` as a publishing
   library if the digest survives.
6. Archive the package once the digest path, if still wanted, is rebuilt on
   analyst output.

v1 gated this freeze on reproducing a digest from canonical analyst records,
which depended on a later phase. Decouple them: freeze now, rebuild later.

### `research-store`

The only runtime consumer is the analyst's
`services/tools/distill_adapter.py`. `ToolRegistry` also boots from
`packages/research-store/distill_tool/tool_schema.json`. The Slice 2
`argument_graph` tool is analyst-local and does **not** need this package;
`research_search` and registry init still do.

Its default corpus path
`packages/research-store/data/distilled_corpus.db` does not exist — that
directory holds `chunks.sqlite`, `embeddings.npz`, and `sample_text.md`. The
adapter catches only `ImportError`, so a missing corpus raises
`sqlite3.OperationalError: no such table: chunks` out of `distill_tool/api.py`
rather than degrading gracefully.

1. Verify first: unset `DISTILL_DB_PATH` and call `research_corpus_info`. If it
   raises, this retrieval tool has been dead and there is no working behavior to
   preserve.
2. Either way, make the adapter fail loudly instead of pretending an empty
   corpus.
3. Move `tool_schema.json` (or an analyst-local copy of the `research_search` /
   `research_corpus_info` specs) out of this package **before** deleting it, so
   `ToolRegistry()` still constructs. `argument_graph` already registers
   in-process and can stay.
4. Stop and remove the `research-store-indexer-1` container, which has been up
   for roughly three weeks running `distill-index-supabase --continuous` from
   `research_processing/research-store`. This is a live worker writing
   `parsed_research` index columns, not a dormant compose service, so confirm
   nothing depends on those columns before stopping it.
5. Preserve the hybrid ranking in `distill_tool/search.py` and the three judged
   queries in `eval/queries.jsonl` by moving them into the canonical retrieval
   module. A three-query eval set does not warrant a formal parity window.
6. Delete the package. `chunks.sqlite` and `embeddings.npz` must not survive as
   a second long-lived corpus.

## Phase 2 — local PostgreSQL and the parser port

The parser is the only writer of canonical source data, so it goes first.

1. Add the root-level `postgres` compose service and apply the consolidated
   schema from Phase 0's decisions. That schema excludes parser 004's unused
   claims/entities/relations tables; claims stay analyst-owned and land in
   Phase 3 with the maps.
2. Port the parser's four tables. The upserts in `src/storage/supabase.py` are
   generic enough to become plain `psycopg` writes; the work is mechanical.
3. Put those writes behind a `SourceStore` interface so `pipeline.py` stops
   calling storage inline. This is small, and it is the abstraction v1 assumed
   already existed.
4. Re-derive: clear `processed_files` and re-parse from Drive.
5. Remove `supabase-py` from the parser and drop `SUPABASE_URL` and
   `SUPABASE_KEY` from its required configuration.

Verification: the re-parsed corpus has the expected document count, and the
parser's existing test suite passes against PostgreSQL. No dual-read, no shadow
mode.

## Phase 3 — analyst: repository seam, then consolidation

The largest piece of work in this plan, and the one v1 most understated.

1. **Extract the repository seam first.** Split `AnalysisStore` by domain — runs,
   chunks and evidence, assertions, world graph, forecasts, dispatch, and the
   Slice 2 consensus tables (`consensus_cluster_state`,
   `consensus_shift_events`, `shadow_street_digest`) — behind interfaces, and
   remove the `store._connect()` reach-through in `DispatchBatchExporter`.
   Consensus and divergence *points* are still queries over `argument_map`, not
   extra tables. This is worth doing independently of the database change and is
   mandatory before it. The god class grew with Slice 2; the split is larger,
   not different in kind.
2. **Port the reads.** Replace the raw PostgREST clients in
   `db/parsed_db_client.py` and `db/calendar_db_client.py` with PostgreSQL
   queries against the Phase 2 schema.
3. **Consolidate the semantic layer.** Move the durable analysis tables out of
   `data/analysis.db` and into the same PostgreSQL instance, including the
   Slice 2 tables above and `document_analysis` (argument maps live in
   `payload_json`). This is the step that actually delivers one semantic store
   per document version.
4. Keep `evals/eval.db`, `evals/golden/` (including `consensus.jsonl`), and
   local caches on SQLite. Those are genuinely operational. Do not port the
   Slice 3 linters, `ArgumentJudge`, or rubric report onto PostgreSQL.
5. Re-run the analyst over the re-parsed corpus.

The JSON dispatch-batch bridge stays through this phase. It works, it is already
the analyst-to-dispatcher contract — including `street_agrees_splits` gated by
`DIGEST_CONSENSUS_MODE` — and retiring it is Phase 4's business.

## Phase 4 — dispatcher narrowing

Mostly default flips plus one deletion.

1. Flip `RESEARCH_DISPATCHER_INPUT_MODE` to default to `analyst`.
2. Flip `LEGACY_SYNTHESIZED_UPDATES` to default to `false`.
3. Delete `mark_as_synthesized()` and the parser-mode query path in
   `src/database.py`. That removes the dispatcher's `supabase-py` client
   entirely.
4. Delete the retired feedback and document-viewer surface: the link injection at
   `src/pdf_generator.py:366-393`, the `FEEDBACK_*` and `DOCUMENT_*` settings and
   validation in `config.py` (including the hardcoded project URL default at
   `config.py:143`), and the cases in `tests/test_pdf_generator.py:58-69`.
5. Move the `pipeline_ops` schema into local PostgreSQL, then delete
   `packages/research_dispatcher/supabase/` entirely — functions, storage,
   `001_create_report_feedback.sql`, the committed `.temp/` CLI cache, and the
   stray `.DS_Store`. Moving `pipeline_ops` off PostgREST also fixes the 406
   errors in `cron.log` caused by a non-public schema not being exposed.

Once analyst records live in PostgreSQL, the JSON file bridge can optionally be
replaced by a read keyed on `batch_key` and `analysis_version`. Worth doing only
after Phase 3; before then it buys nothing.

The dispatcher is retained, not archived. It remains the report and delivery
adapter: cross-document throughlines and callouts, PDF and report formatting,
email delivery, and dispatch history. Document eligibility stays analyst-owned.

Reader feedback is no longer a dispatcher capability. Earlier versions of this
plan listed it among the responsibilities to retain, but it only ever worked
through the retired Edge Function, and `report_feedback` has no reader in the
pipeline. If reader feedback is wanted later, it is new work against the local
stack, not a capability being preserved.

## Phase 5 — drop Supabase

Gate: no package imports a Supabase client, no configuration references
`SUPABASE_URL` or `SUPABASE_KEY`, and the local stack has completed one full
parse → analyze → dispatch run.

Then remove `SUPABASE_*` from the root `.env.example`, delete the tracked CLI
cache at `packages/research_dispatcher/supabase/.temp/` along with the stray
`.DS_Store`, retain the final export offline, and delete the hosted project.

## Parallel track — relay privacy boundary and pipeline intake

Independent of the Supabase work. It shares no code with the migration and
should not queue behind it.

**R1. Attachment document-metadata sanitization, fail-closed.** This is the one
unimplemented requirement in
`packages/research-relay/docs/superpowers/specs/2026-09-20-sanitization-requirements.md`
(items 7 and 9). Header stripping, address redaction, quoted-history removal,
filename sanitization, and prohibited-type blocking are already implemented in
`reconstruct.py`, `redact.py`, `quotes.py`, and `attachments.py`. Metadata
scrubbing is not. Relay is live and the README now claims a boundary the code
does not enforce, which makes this the highest-severity item in the plan.

**R2. Relay to parser intake contract.** Define the intake artifact — relay
ledger key, post-sanitization content hash, sanitized body and subject,
attachment manifest, and original date when parseable — and add it as a second
parser intake adapter alongside Drive polling. This is the additive parser change
the protected-core rule permits, and it is what makes the objective diagram true.

**R3. Intake idempotency.** Replaying a relay key must not create a second
downstream artifact. Already an acceptance criterion in the spec; assert it at
the parser boundary as well.

Relay must not write claims, themes, analyst state, or dispatch state, and
downstream packages must never fall back to the original private message.

## Verification, right-sized

v1 specified dual-read, shadow mode, parity windows, and one full operational
cycle without consumers. For a pre-production system with no external consumers,
that ceremony costs more than it protects. Replace it with:

- a retained Supabase export until the local stack completes one full run
- the existing package test suites, run against PostgreSQL
- one end-to-end run: parse → analyze → dispatch, producing a report
- a document-count sanity check after re-derivation

There is no CI in this repository — no `.github/workflows`, no other pipeline
config. Every gate above is therefore a manual step, and the test suites have no
standing green baseline to compare against. Before Phase 2, record a passing
baseline per package on the current Supabase-backed code, so that "the tests pass
against PostgreSQL" is a comparison rather than an assertion. A minimal workflow
that runs the suites on push is worth considering ahead of a migration of this
size, but it is a judgment call, not a prerequisite.

Reintroduce parity gates and rollback windows when there is a production
consumer to protect. That is a pre-production-launch task, not a now task.

## Priority order

1. Phase 0 decision 1, reconciling the deployment checkout. Nothing else has any
   production effect until this is done.
2. R1 sanitization. A live privacy gap, independent of everything else.
3. The remaining Phase 0 decisions (1, 2, 3, 5, 6), plus a recorded test
   baseline. Decision 4 is already settled.
4. Phase 1 pruning. Removes two Supabase clients before they need porting, and
   decommissions two live jobs.
5. Phase 2 parser port onto local PostgreSQL.
6. Phase 3 analyst repository seam and consolidation. The long pole.
7. Phase 4 dispatcher narrowing, which removes the last Supabase client.
8. Phase 5 drop the hosted project.
9. R2 and R3 relay intake, at any point after R1.
