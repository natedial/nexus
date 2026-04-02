# Dispatcher / Analyst Refactor Plan

Last updated: 2026-04-01 America/New_York

## Goal

Refactor `research_dispatcher` around the introduction of `research_analyst` so that:

- `research_analyst` owns document readiness, quality gating, assertion extraction, graph state, forecast staging, and prompt-ready evidence preparation
- `research_dispatcher` owns cross-document editorial synthesis, throughline assembly, report formatting, PDF generation, and email delivery
- dispatcher throughlines improve because they can now consider richer analyst-produced signals rather than only parser-era themes and trades

## Executive Recommendation

Do not move throughline assembly out of dispatcher.

That remains the right boundary because throughlines are a report-window, cross-document editorial product rather than a durable document-analysis primitive.

But dispatcher should stop building throughlines directly from raw `parsed_research` rows.

Opinionated recommendation:

- keep the LLM-driven throughline writer in `research_dispatcher`
- move document selection and evidence preparation upstream into `research_analyst`
- introduce an explicit analyst-to-dispatcher `DispatchBatch` contract
- refactor dispatcher to consume analyst-prepared evidence packs instead of reconstructing synthesis inputs from `parsed_data`

This is the highest-leverage change because it preserves the strongest part of dispatcher while removing the weakest part of its current architecture.

## Why The Current Split Is Wrong

Today dispatcher still acts as:

1. a document selector
2. a synthesis-input constructor
3. a report renderer and sender

That made sense before `research_analyst` existed.

It is now the wrong shape.

Current mismatches:

- [src/main.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/main.py) still treats `parsed_research` as the main unit of work and uses dispatcher-time document marking
- [src/database.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/database.py) still polls parser-owned storage as if it were report-ready analysis storage
- [src/synthesizer.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/synthesizer.py) still rebuilds the synthesis substrate from raw themes and trades
- [src/formatter.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/formatter.py) still performs business aggregation directly on parser-shaped payloads

At the same time, `research_analyst` already owns:

- batch selection and reprocessing
- document quality review
- chunking and evidence extraction
- assertion extraction
- graph updates and lifecycle tracking
- forecast candidate staging and upload review
- local review payload generation

The code already reflects that boundary:

- [research_analyst/src/research_analysis_layer/pipelines/run_batch.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/run_batch.py)
- [research_analyst/src/research_analysis_layer/pipelines/analyze_document.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/analyze_document.py)
- [research_analyst/src/research_analysis_layer/db/analysis_store.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/db/analysis_store.py)

## Target Boundary

### `research_parser` owns

- PDF ingestion
- raw text parsing
- metadata extraction
- normalized theme extraction
- trade extraction
- parsed content persistence

### `research_analyst` owns

- readiness and quality gating
- batch selection and watermarking
- backfill and reprocess workflows
- chunking
- evidence units
- assertions
- node and edge resolution
- forecast extraction and staging
- prompt-ready evidence preparation for downstream reporting

### `research_dispatcher` owns

- dispatch-window scoping
- cross-document editorial framing
- throughline assembly
- callout extraction
- report formatting and layout
- PDF generation
- delivery
- dispatch-specific history and deltas

## Non-Goals

This plan does not include:

- moving final editorial synthesis into `research_analyst`
- replacing ReportLab or email delivery
- exposing the world model directly to end users
- rewriting parser storage contracts
- making dispatcher write graph or assertion state

## Core Design Change

Replace dispatcher's current raw-row input path with an analyst-owned export contract.

Dispatcher should not query arbitrary analyst internals ad hoc.

It should consume one explicit contract for one dispatch run:

- selected documents
- quality-qualified evidence
- compact cross-document reasoning inputs
- forecast and event context
- document metadata suitable for reporting

## Proposed Contract: `DispatchBatch`

### Top-level shape

```json
{
  "batch_key": "2026-04-01:US:rates:7d",
  "analysis_version": "2026-03-31",
  "generated_at": "2026-04-01T08:55:00Z",
  "scope": {
    "date_from": "2026-03-25",
    "date_to": "2026-04-01",
    "region": "US",
    "asset_focus": "rates",
    "sources": ["Goldman Sachs", "JPMorgan"]
  },
  "documents": [],
  "cross_document_signals": {
    "repeated_assertions": [],
    "contested_assertions": [],
    "reinforced_edges": [],
    "event_clusters": []
  }
}
```

### Per-document shape

Each `documents[]` item should include:

- `research_id`
- `document_hash`
- `file_id`
- `document_name`
- `source`
- `source_date`
- `publisher`
- `region`
- `asset_focus`
- `document_link`
- `quality`
- `themes`
- `trades`
- `assertions`
- `world_nodes`
- `world_edges`
- `forecast_candidates`

### Quality block

```json
{
  "score": 84,
  "passed": true,
  "warnings": ["sparse_trade_coverage"],
  "blocking_issues": []
}
```

### Theme block

Keep themes recognizable to dispatcher, but richer:

```json
{
  "label": "Higher term premium",
  "context": "Term premium is repricing as supply and fiscal risk remain sticky.",
  "strength": "Primary",
  "confidence": "High",
  "classification": "forecast",
  "relevance": ["rates", "macro"],
  "directionality": {"bearish_bonds": 2},
  "excerpts": ["..."],
  "theme_order": 1
}
```

### Assertion block

Assertions are the most important new input to throughline assembly.

```json
{
  "chunk_order": 2,
  "assertion_order": 1,
  "assertion_type": "forecast",
  "summary_text": "March payroll growth should undershoot consensus.",
  "text": "...",
  "status": "proposed",
  "authority_band": "seed",
  "time_horizon": "days",
  "time_anchor": "2026-04-03",
  "condition_text": null,
  "qualifier_text": "if weather distortions reverse"
}
```

### World structure block

Dispatcher should consume only the subset relevant for synthesis:

- nodes tied to exported assertions
- edges tied to exported assertions
- support counts
- authority bands
- relationship types

This gives throughlines a causal and contradiction-aware substrate rather than a label-only substrate.

## What Dispatcher Should Do With The New Contract

### Keep

- final throughline writing in [src/synthesizer.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/synthesizer.py)
- callout extraction
- synthesis delta tracking in [src/delta_engine.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/delta_engine.py)
- report formatting and rendering

### Remove

- direct dependence on `parsed_research` as the synthesis substrate
- assumption that `parsed_data.themes` and `parsed_data.trades` are the only meaningful evidence
- use of parser-owned `synthesized` as the main dispatch work queue and acknowledgement mechanism

### Add

- an analyst batch client
- report DTOs
- deterministic pre-clustering before LLM synthesis
- dispatch-owned run ledger

## Recommended `research_dispatcher` Module Changes

### New modules

Add:

- `src/analyst_client.py`
  - loads an analyst-produced `DispatchBatch`
  - can support file-based JSON first, service/API later
- `src/report_models.py`
  - typed dataclasses for `DispatchBatch`, `DispatchDocument`, `ThroughlineCandidateCluster`, `ReportData`
- `src/throughline_input_builder.py`
  - converts analyst evidence into compact prompt payloads
- `src/dispatch_store.py`
  - local SQLite ledger for dispatch runs, batch keys, sent reports, and document coverage

### Refactor existing modules

#### [src/main.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/main.py)

Change from:

- query parser-owned records
- synthesize
- format
- email
- mark rows synthesized

To:

- load analyst dispatch batch
- build throughline input
- synthesize
- format
- email
- persist dispatch run state

#### [src/database.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/database.py)

Short-term:

- keep only calendar/event queries here

Long-term:

- rename or split this module because it is no longer the primary analysis fetch layer

#### [src/formatter.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/formatter.py)

Change from:

- raw parser-row aggregation

To:

- formatting of already-resolved `DispatchBatch` / `ReportData`

It should become presentation-oriented, not inference-oriented.

#### [src/synthesizer.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/synthesizer.py)

Keep the editorial LLM stages.

Refactor input preparation:

- replace `_prepare_input(documents)` with a builder that accepts `DispatchBatch`
- preserve the stage 1 / editor / analyst / callout chain
- improve deterministic clustering before stage 1

## Throughline Assembly: The Gold Standard Version

The best version of dispatcher throughline assembly is not:

- raw themes in
- LLM does everything

It is:

1. analyst exports report-quality evidence
2. dispatcher performs deterministic cross-document clustering
3. dispatcher ranks clusters by signal
4. LLM writes throughlines from those ranked clusters
5. LLM extracts callouts from the throughlines

### Deterministic pre-clustering

Create candidate cross-document clusters using:

- shared normalized theme labels
- shared assertion summaries
- shared world nodes
- shared world edges
- shared forecast indicators or matched events
- contradiction signals from opposing assertions or edge statuses

This step should happen before the LLM sees the corpus.

### Rank clusters using explicit heuristics

Each cluster should receive a deterministic score using:

- source diversity
- recency
- quality-weighted support
- authority-weighted support
- contradiction intensity
- calendar/event relevance
- PM relevance heuristics

Opinionated recommendation:

- treat consensus plus fracture as the default ranking winner
- pure repetition without tension should rank lower than repeated evidence with a live disagreement or pending signpost

### Build compact evidence packs

For each cluster, pass only the best evidence:

- top 3 to 6 supporting sources
- top 2 to 4 excerpts
- top assertions
- linked forecasts or event anchors
- strongest node or edge labels

This gives the model a cleaner substrate and reduces token waste.

### Let the LLM do the editorial work

The model should be asked to:

- choose the most important clusters
- frame the consensus
- identify what breaks the consensus
- write the PM-facing throughline
- preserve grounding to supplied evidence

That is exactly the kind of task dispatcher should continue to own.

## How Throughlines Improve With Analyst Data

Today dispatcher mostly sees:

- theme labels
- theme contexts
- trades
- source names

With analyst integration, it can reason over:

- explicit forecasts rather than only forecast-like themes
- repeated assertions across sources
- contradictory assertions across sources
- causal or impact relationships via world edges
- evidence provenance via chunk summaries and excerpts
- quality-gated notes instead of treating every note equally
- event-linked timing and release windows

This materially improves throughline quality in four ways:

### 1. Better consensus detection

Consensus should be inferred from repeated assertions and repeated causal edges, not just repeated theme labels.

### 2. Better fracture detection

Fractures should be driven by contradictory forecasts, opposite qualifiers, contested edges, or different time horizons.

### 3. Better timing

Dispatcher can tie throughlines to upcoming economic or supply events with more confidence.

### 4. Better ranking

High-quality, high-authority, multi-source signals should outrank thin repetition from weak notes.

## New Dispatcher-Owned Dispatch Ledger

Dispatcher should stop using parser-owned `synthesized` as its primary state mechanism.

Add a local dispatcher store with:

- `dispatch_runs`
- `dispatch_run_items`
- `dispatch_snapshots`

Recommended tracked fields:

- `batch_key`
- `analysis_version`
- `report_scope_json`
- `document_count`
- `throughline_count`
- `callout_count`
- `pdf_path`
- `sent_to`
- `created_at`

Per-document coverage should track:

- `research_id`
- `document_hash`
- `included_in_batch_key`
- `dispatch_run_id`

Why:

- dispatch is a downstream reporting concern
- it should not overload parser state
- it must be able to rerun a report window without mutating upstream content state

## Phased Migration Plan

## Phase 1: Add the contract without breaking report delivery

Files:

- add `src/report_models.py`
- add `src/analyst_client.py`
- add `src/throughline_input_builder.py`

Tasks:

- define the `DispatchBatch` dataclasses
- support reading a file-based JSON export first
- add a compatibility adapter so dispatcher can still run in legacy mode

Acceptance criteria:

- dispatcher can consume either legacy parser rows or analyst batch input
- no PDF or email code changes required yet

## Phase 2: Move synthesis input building onto analyst batch data

Files:

- [src/synthesizer.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/synthesizer.py)

Tasks:

- replace raw-row `_prepare_input()` assumptions
- add deterministic cluster building from assertions, nodes, edges, forecasts, and themes
- add cluster scoring
- feed only compact cluster evidence into stage 1

Acceptance criteria:

- throughline payloads are materially smaller and higher-signal
- stage 1 can reference assertion and forecast evidence, not just themes

## Phase 3: Refactor formatter around report DTOs

Files:

- [src/formatter.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/formatter.py)

Tasks:

- remove parser-shape assumptions from report formatting
- compute summary, details, themes, and trades from `DispatchBatch`
- add optional analyst-informed sections later without breaking layout

Acceptance criteria:

- formatter is presentation-oriented
- report data no longer depends on `parsed_data`

## Phase 4: Introduce dispatch-owned run tracking

Files:

- add `src/dispatch_store.py`
- update [src/main.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/main.py)

Tasks:

- persist dispatch runs and per-document coverage
- save report metadata and synthesis snapshots
- stop using parser-owned `synthesized` for primary dispatch acknowledgement

Acceptance criteria:

- report reruns no longer require mutating parser tables
- dispatcher can answer “what was sent when” on its own

## Phase 5: Remove legacy fetch path

Files:

- [src/database.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/database.py)
- [src/main.py](/Users/ncdial/devwork/research_processing/research_dispatcher/src/main.py)

Tasks:

- delete legacy direct `parsed_research` synthesis path after analyst batch mode is proven
- keep only calendar/event queries and any minimal shared lookups

Acceptance criteria:

- dispatcher no longer depends on parser row shape for report assembly

## What `research_analyst` Should Add Next

To support this refactor cleanly, analyst should add an export layer.

Recommended additions:

- `export-dispatch-batch`
  - emits one JSON payload for a requested scope
- deterministic cross-document helper queries
  - repeated assertions
  - contested assertions
  - reinforced edges
  - event-linked forecast clusters
- score or filter helpers
  - “fresh + high-authority + multi-source”

This can begin as a CLI JSON export before any service boundary exists.

## Testing Strategy

Add dispatcher tests for:

- analyst batch parsing
- legacy compatibility mode
- cluster scoring and ranking
- throughline input compaction
- formatter behavior over report DTOs
- dispatch ledger writes

Recommended new test files:

- `tests/test_analyst_client.py`
- `tests/test_throughline_input_builder.py`
- `tests/test_dispatch_store.py`
- `tests/test_formatter_dispatch_batch.py`

## Risks

### Risk 1: Overloading analyst with editorial logic

Avoid this.

Analyst should prepare evidence, not write final throughlines.

### Risk 2: Passing too much graph detail to dispatcher

Avoid exporting the full graph.

Only export the document-linked and cluster-relevant subset.

### Risk 3: Big-bang migration

Avoid this.

Run legacy mode and analyst-batch mode side by side first.

### Risk 4: Recreating raw-row assumptions inside the new contract

Avoid carrying `parsed_data` through as an opaque blob.

The new contract should be explicit and typed.

## Acceptance Criteria

This refactor is successful when:

- dispatcher still owns and writes the final throughlines
- throughline inputs include analyst-produced assertions, graph hints, and forecast context
- dispatcher no longer relies on parser-owned `synthesized` as its main state mechanism
- formatter and synthesizer operate on stable report DTOs rather than raw parser rows
- analyst can export one prompt-ready batch per dispatch window
- the resulting throughlines are more specific, better timed, and better grounded than the current theme-only path

## Immediate Next Step

Implement Phase 1 first.

Opinionated recommendation:

- do not start by rewriting prompts
- do not start by changing PDF layout
- first lock the analyst-to-dispatcher contract and wire dispatcher to consume it

Once the input contract is stable, prompt tuning and throughline-quality upgrades become much easier and much safer.
