# Analysis Layer Implementation Plan

Last updated: 2026-03-26 America/New_York

## Goal

Turn this repository into the implementation and management layer between `research_parser` and `research_dispatcher`.

This layer should:

- detect newly successful parser outputs via `state.db`
- fetch authoritative parsed content from the parsed database
- analyze documents in topical chunks rather than as whole-note blobs
- extract assertions and evidence from those chunks
- maintain a durable, evolving world model of concepts and relationships
- preserve provenance so downstream systems can inspect why a node or edge exists
- improve synthesis quality and signal distillation for better decision making

## Repo role

This repo should be treated as the future home of the analysis/enrichment service.

The intended boundary is:

- `research_parser`
  - extracts document facts
  - owns normalized parsed content
  - writes parser run status to `state.db`

- this repo
  - detects new parser-complete documents
  - hydrates normalized content from the parsed database
  - performs chunking, assertion extraction, and graph maintenance
  - tracks its own run state, retries, and backfills

- `research_dispatcher`
  - consumes analysis-layer outputs later for synthesis and reporting
  - should not own durable graph construction

## Product intent

The analysis layer is not just a document-local linker.

Its long-term function is to build and maintain a market world model that behaves more like analyst memory:

- new documents add evidence
- assertions begin as tentative paths
- repeated support strengthens relationships
- contradictions contest but do not erase accumulated structure
- time can decay unsupported forecasts
- realized events and data can harden, reinterpret, or invalidate prior views
- ambiguity should generate explicit `open_question` records rather than overconfident implications

## Planning posture

This plan intentionally separates:

- immediate implementation scope
- medium-term world-model expansion
- out-of-scope work for the first operating versions

That split is important because the full vision is broader than the existing 2026-03-22 document-local theme-link spec.

## Core operating model

### Triggering

- cron-based background job
- `state.db` is used only for change detection and job discovery
- authoritative content must be fetched from the parsed database

### Unit of processing

- batch runs should be preferred operationally
- within a batch, one `research_id` is still the atomic document work unit
- within a document, `analysis_chunk` is the analysis boundary
- within a chunk, `assertion` is the semantic unit

### Provenance chain

Recommended logical chain:

- `source_document`
- `analysis_chunk`
- `evidence_unit`
- `assertion`
- `world_node`
- `world_edge`

### Graph/world-model posture

- prefer soft canonicalization over hard identity collapse
- allow unconnected nodes and weak proposed edges
- require evidence accumulation for stronger standing
- preserve time and reinterpretation history
- emit unresolved questions when inference is weak

## Recommended v1 world-model primitives

### Core records

- `source_document`
- `analysis_chunk`
- `evidence_unit`
- `assertion`
- `world_node`
- `world_edge`
- `analysis_run`

### Recommended `world_node` types

- `concept`
- `event`
- `forecast`
- `realized_data_point`
- `market_impact`
- `entity`
- `instrument`
- `open_question`

### Recommended `world_edge` types

- `same_idea_as`
- `related_to`
- `supports`
- `contradicts`
- `qualifies`
- `drives`
- `implies`
- `reacts_to`
- `forecasts`
- `realized_as`
- `impacts`
- `raises_question`

## Assertion lifecycle model

Use two explicit axes:

- `assertion_state`
  - `proposed`
  - `supported`
  - `reinforced`
  - `contested`
  - `stale`
  - `invalidated`

- `authority_band`
  - `seed`
  - `emerging`
  - `established`
  - `core`
  - `structural`

Also track supporting metrics internally:

- `authority_score`
- `support_count`
- `contradiction_count`
- `source_diversity`
- `last_supported_at`
- `last_contested_at`
- `regime_count`

Opinionated recommendation:

- `state` should move faster than `authority`
- `authority` should be hard to earn and slow to lose
- old but contested ideas should not immediately collapse to zero standing

## Chunking model

This repo should analyze by chunk, not by full document.

The chunk taxonomy is defined in:

- [2026-03-26-analysis-chunk-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-chunk-taxonomy-spec.md)

Key principles:

- chunk by topic and argument coherence
- preserve source order
- one chunk can yield multiple assertions
- use deterministic boundaries first
- avoid fixed-size chunking as the default

## Phase model

## Phase 0: Validate inputs and write the local contracts

Goal:

- reduce ambiguity before implementation starts

Tasks:

- confirm parser `state.db` shape and success-state semantics
- confirm parsed database access path and credentials model
- inspect real parser outputs across 20-30 representative notes
- validate that normalized themes/excerpts contain enough information for chunking
- identify when raw content fallback is necessary
- lock the logical contracts for `analysis_chunk`, `evidence_unit`, `assertion`, `world_node`, and `world_edge`

Acceptance criteria:

- trigger source is fully understood
- parsed DB hydration path is documented
- at least one sample corpus review has been completed
- logical contracts are written and stable enough for implementation

## Phase 1: Build the cron worker and document ingestion loop

Goal:

- make the service operational as a background job

Tasks:

- create a scheduled CLI entrypoint
- read `state.db` for newly successful parser rows
- persist local analysis run state
- batch eligible `research_id` values
- fetch normalized document content from parsed DB
- implement idempotent document claiming and rerun checks
- support manual backfill mode by date/source/id

Acceptance criteria:

- cron job can detect new work
- reruns are safe
- failures are recorded without losing operational visibility
- manual backfill is possible without code changes

## Phase 2: Add chunking and assertion extraction

Goal:

- move from document ingestion to meaningful analysis units

Tasks:

- implement `analysis_chunk` extraction using the chunk taxonomy spec
- derive `evidence_unit` records from excerpts and parser context
- extract assertions from chunks
- classify assertions by type
- preserve conditions, qualifiers, and horizons
- allow zero-assertion chunks when content is low signal

Acceptance criteria:

- multi-topic notes split into coherent chunks
- assertions are attributable to specific chunk evidence
- forecasts, interpretations, trade claims, and risks are separable in common notes

## Phase 3: Implement document-local relationship extraction

Goal:

- preserve the useful part of the original theme-linker scope as an early milestone

Tasks:

- map theme/assertion pairs inside a document
- infer document-local relationships such as `supports`, `contradicts`, `qualifies`, and `drives`
- retain provenance to chunks and evidence units
- decide which outputs should still write into `research_theme_links` versus local analysis tables

Acceptance criteria:

- document-local structure is generated deterministically
- relationships are auditable and evidence-backed
- the service improves local coherence before cross-document graph work

## Phase 4: Introduce soft world-node resolution

Goal:

- start building the cross-document model without overcommitting to hard ontology decisions

Tasks:

- add matching logic from assertions to existing `world_node`s
- create new nodes when no good existing match is found
- support soft relationships like `same_idea_as` and `related_to`
- preserve competing concepts when confidence is low
- attach provenance and initial lifecycle state

Acceptance criteria:

- repeated ideas across documents can accumulate around shared nodes
- low-confidence matches do not force incorrect canonicalization
- competing interpretations can coexist

## Phase 5: Add world-edge reinforcement and temporal updates

Goal:

- let the model mature across time rather than just store disconnected outputs

Tasks:

- reinforce edges when independent evidence repeats
- contest edges when contradictory evidence arrives
- decay unsupported forecasts over time
- harden forecast and impact links when later realized evidence appears
- track regime survival and reinterpretation history
- emit `open_question` nodes where repeated ambiguity remains

Acceptance criteria:

- edges can gain or lose standing over time
- forecast-versus-realization dynamics are represented
- unresolved uncertainty is preserved explicitly

## Phase 6: Prepare downstream consumption

Goal:

- make the analysis layer useful to `research_dispatcher` and analyst workflows

Tasks:

- define retrieval views for synthesis
- define query patterns for concept-centric and event-centric lookups
- add “fresh + high-authority + contested” style filters
- expose prompt-ready payloads for synthesis experiments
- document how dispatcher should consume world-model outputs without owning them

Acceptance criteria:

- at least one downstream synthesis use case can read from this layer
- the graph improves signal distillation rather than just storing structure

## Explicit v1 recommendation

To keep momentum and avoid overbuilding, the first implementation milestone should stop at:

- Phase 1
- Phase 2
- Phase 3
- the simplest useful slice of Phase 4

That means:

- cron ingestion works
- chunking works
- assertion extraction works
- document-local relationships exist
- soft world-node creation begins

Do not try to solve full cross-document causal reasoning in the first pass.

## Non-goals for the first implementation pass

- user-facing graph editing UI
- fully automated high-confidence ontology construction
- deep regime classification from day one
- hard canonical merges without evidence review
- autonomous portfolio decisioning
- replacing `research_dispatcher` synthesis logic immediately

## Open design questions

- should the first persistence layer live beside existing parser-owned tables or in analysis-owned tables only
- how much raw text should be copied locally versus referenced remotely
- when should a relationship write to `research_theme_links` versus only to analysis-native structures
- whether concept resolution should begin with deterministic rules, embeddings, or tightly constrained LLM classification
- how to define source independence when multiple notes come from the same institution

## Suggested module layout

If implemented as a Python package in this repo:

```text
research_analysis_layer/
  src/
    main.py
    config.py
    scheduler.py
    state_reader.py
    selector.py
    parser_client.py
    chunker.py
    evidence.py
    assertion_extractor.py
    resolver.py
    graph_updater.py
    lifecycle.py
    writer.py
    models.py
  tests/
    test_state_reader.py
    test_selector.py
    test_chunker.py
    test_assertion_extractor.py
    test_resolver.py
    test_graph_updater.py
    test_lifecycle.py
```

## To-do list

### Immediate

- confirm the schema and semantics of parser `state.db`
- document the parsed DB tables and access path this repo must read
- write a dedicated assertion taxonomy spec
- write a persistence/schema draft for analysis-owned tables
- define analysis run statuses and rerun rules
- collect 20-30 representative parser outputs for chunking review

### Near-term build

- scaffold Python package layout
- implement config loading and environment handling
- implement `state.db` polling
- implement parsed DB hydration client
- implement local run-state storage
- implement manual backfill CLI
- implement deterministic chunk boundary heuristics
- implement `analysis_chunk` persistence
- implement `evidence_unit` derivation
- implement assertion extraction

### Graph bootstrap

- define initial `world_node` and `world_edge` schemas
- implement soft node matching
- implement weak edge creation with provenance
- implement lifecycle state transitions
- implement authority scoring and banding
- implement temporal decay rules for forecasts
- implement open-question generation

### Validation

- build a review harness showing document text, chunks, assertions, and graph updates
- manually review at least 25 processed documents
- measure chunk-count distribution per note
- measure assertion-count distribution per chunk
- inspect false merges and false splits in world-node resolution
- inspect whether authority changes feel intuitive on reprocessing

### Downstream readiness

- define one synthesis-oriented retrieval query
- define one analyst QA query
- define one concept timeline query
- document the initial dispatcher integration contract

## Milestone checklist

### Milestone A: Operational ingestion

- cron worker runs
- new successful parser docs are detected
- parsed DB hydration succeeds
- local run tracking works

### Milestone B: Chunked analysis

- documents split into coherent chunks
- evidence units are stored
- assertions are extracted reliably

### Milestone C: Local structure

- document-local relationships are extracted
- provenance is preserved
- output is manually reviewable

### Milestone D: Early world model

- assertions map into `world_node`s
- weak cross-document edges accumulate
- lifecycle and authority fields update over time

### Milestone E: Synthesis utility

- dispatcher or analyst workflows can retrieve useful higher-signal structures from this layer

## Related documents

- [2026-03-29-analysis-planning-round-closeout-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-planning-round-closeout-plan.md)
- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)
- [2026-03-22-theme-link-enrichment-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-22-theme-link-enrichment-spec.md)
- [2026-03-22-theme-normalization-migration-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-22-theme-normalization-migration-plan.md)
- [2026-03-26-analysis-chunk-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-chunk-taxonomy-spec.md)

## Planning round note

This March 26 document is the umbrella framing artifact for the analysis-layer effort.

The executable planning handoff now lives in the March 27 to March 29 spec set, especially:

- [2026-03-29-analysis-planning-round-closeout-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-planning-round-closeout-plan.md)
- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)

## Status

`SUPERSEDED_BY_MARCH_27_29_SPEC_SET`
