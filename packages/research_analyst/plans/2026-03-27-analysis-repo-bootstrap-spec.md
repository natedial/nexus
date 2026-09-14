# Analysis Repo Bootstrap Spec

Last updated: 2026-03-27 America/New_York

## Goal

Define the initial package layout, module responsibilities, interfaces, and implementation sequence for the first coding agent.

This document is the bridge between architecture plans and actual code scaffolding.

## Build posture

Start with a simple Python service package and one CLI entrypoint.

Recommended runtime:

- Python 3.11
- `pydantic`
- `sqlalchemy` or direct SQL client depending on team preference
- `structlog`
- `tenacity`
- `typer` or `argparse` for CLI

Keep external dependencies narrow in the first pass.

## Initial package layout

```text
research_analysis_layer/
  pyproject.toml
  README.md
  src/
    research_analysis_layer/
      __init__.py
      main.py
      config.py
      logging.py
      clocks.py
      models/
        __init__.py
        run_models.py
        document_models.py
        chunk_models.py
        assertion_models.py
        world_models.py
      db/
        __init__.py
        analysis_store.py
        parsed_db_client.py
        state_db_reader.py
        migrations/
      services/
        __init__.py
        selector.py
        hydrator.py
        chunker.py
        evidence_builder.py
        assertion_extractor.py
        resolver.py
        graph_updater.py
        lifecycle.py
        backfill.py
        reconcile.py
      pipelines/
        __init__.py
        analyze_document.py
        run_batch.py
      prompts/
        assertion_extraction.md
      tests/
        test_selector.py
        test_chunker.py
        test_assertion_extractor.py
        test_resolver.py
        test_graph_updater.py
```

## CLI commands

Recommended initial commands:

- `run`
  - normal cron-triggered batch run

- `backfill`
  - date/source windowed replay

- `reprocess`
  - rerun one `research_id` or `document_hash`

- `reconcile`
  - compare parser-success corpus against analysis-owned records

- `doctor`
  - quick operational checks for credentials, database reachability, and schema presence

## Core interfaces

## `Config`

Responsibilities:

- read environment variables
- expose parsed DB credentials
- expose analysis DB credentials
- expose `state.db` path
- expose batch size, retry settings, and version labels

Suggested fields:

- `analysis_db_url`
- `parsed_db_url`
- `state_db_path`
- `batch_size`
- `cron_mode_enabled`
- `analysis_version`
- `chunker_version`
- `assertion_extractor_version`
- `resolver_version`

## `StateDbReader`

Responsibilities:

- read parser success records from `state.db`
- filter by last watermark
- return lightweight selection records only

Suggested methods:

- `get_successful_since(watermark: datetime) -> list[ParserStateRecord]`
- `get_by_research_ids(ids: list[int]) -> list[ParserStateRecord]`

## `ParsedDbClient`

Responsibilities:

- fetch authoritative parsed content for one or more `research_id`s
- keep parser schema access isolated from the rest of the app

Suggested methods:

- `fetch_documents(ids: list[int]) -> list[ParsedDocument]`
- `fetch_themes(ids: list[int]) -> list[ParsedTheme]`
- `fetch_excerpts(theme_ids: list[int]) -> list[ParsedExcerpt]`
- `hydrate_documents(ids: list[int]) -> list[HydratedParsedDocument]`

## `AnalysisStore`

Responsibilities:

- write run state
- replace intermediate per-document analysis records
- upsert world-model records
- enforce provenance uniqueness

Suggested methods:

- `create_run(...) -> AnalysisRun`
- `create_run_items(...)`
- `mark_run_item_processing(...)`
- `replace_document_analysis(...)`
- `upsert_world_nodes(...)`
- `upsert_world_edges(...)`
- `record_edge_history(...)`
- `finalize_run_item(...)`
- `finalize_run(...)`

## `Selector`

Responsibilities:

- combine parser-success signals with analysis-owned state
- decide which documents are eligible now

Suggested methods:

- `select_for_run(...) -> list[SelectionDecision]`
- `select_for_backfill(...) -> list[SelectionDecision]`

## `Chunker`

Responsibilities:

- apply deterministic chunk boundary heuristics
- map document content to ordered `analysis_chunk`s

Suggested methods:

- `chunk_document(doc: HydratedParsedDocument) -> list[AnalysisChunkDraft]`

## `EvidenceBuilder`

Responsibilities:

- derive `evidence_unit`s from chunk content and parser-normalized excerpts

Suggested methods:

- `build_evidence(chunks: list[AnalysisChunkDraft], doc: HydratedParsedDocument) -> list[EvidenceUnitDraft]`

## `AssertionExtractor`

Responsibilities:

- convert chunks plus evidence into structured assertions
- preserve conditions, qualifiers, and horizons

Suggested methods:

- `extract(chunk: AnalysisChunkDraft, evidence: list[EvidenceUnitDraft]) -> list[AssertionDraft]`

## `Resolver`

Responsibilities:

- map assertion subjects and objects into `world_node` candidates
- choose create-vs-reinforce-vs-soft-link behavior

Suggested methods:

- `resolve_nodes(assertions: list[AssertionDraft]) -> list[NodeResolution]`
- `resolve_edges(assertions: list[AssertionDraft], nodes: list[NodeResolution]) -> list[EdgeResolution]`

## `GraphUpdater`

Responsibilities:

- persist node and edge updates
- attach evidence
- keep updates idempotent

Suggested methods:

- `apply_resolutions(...) -> GraphUpdateResult`

## `LifecycleService`

Responsibilities:

- compute status transitions
- compute authority band changes
- compute forecast decay and contradiction effects

Suggested methods:

- `update_node_state(...)`
- `update_edge_state(...)`
- `evaluate_temporal_updates(...)`

## `AnalyzeDocumentPipeline`

Responsibilities:

- orchestrate one document from hydrated input to persisted analysis

Suggested flow:

1. validate document readiness
2. chunk document
3. build evidence
4. extract assertions
5. resolve nodes and edges
6. persist intermediate and world-model updates
7. return counts and status

## `RunBatchPipeline`

Responsibilities:

- manage one operational run from selection to finalization

Suggested flow:

1. create run
2. read parser-success candidates
3. select eligible items
4. process documents one by one
5. finalize run and watermark

## Pydantic model boundaries

Use typed drafts and persisted models separately.

Recommended draft objects:

- `ParserStateRecord`
- `HydratedParsedDocument`
- `AnalysisChunkDraft`
- `EvidenceUnitDraft`
- `AssertionDraft`
- `NodeResolution`
- `EdgeResolution`
- `GraphUpdateResult`

Reason:

- keeps internal pipeline contracts explicit
- reduces accidental coupling to database row shapes

## Suggested test order

1. selector tests
2. chunker tests
3. assertion extractor tests
4. resolver tests
5. graph updater idempotency tests
6. batch pipeline smoke test

## Recommended first coding sequence

### Step 1

- scaffold package
- implement config
- implement logging
- implement CLI shell

### Step 2

- implement `StateDbReader`
- implement `ParsedDbClient`
- implement `AnalysisStore` stubs

### Step 3

- implement run creation/finalization
- implement document selection logic

### Step 4

- implement deterministic chunker
- implement evidence builder

### Step 5

- implement assertion extractor with minimal deterministic or prompt-driven path

### Step 6

- implement minimal resolver for node creation and simple edge creation

### Step 7

- implement idempotent graph updater and lifecycle updates

### Step 8

- add backfill and reconcile commands

## First non-goals for bootstrap

- full-blown async worker framework
- distributed concurrency
- advanced UI or dashboard
- complete LLM-driven ontology resolution
- production-grade prompt optimization before the deterministic path is stable

## Acceptance criteria

This bootstrap spec is sufficient when:

- another agent can scaffold the repo without inventing module boundaries
- the first implementation can run one full document through the pipeline
- future complexity has obvious extension points

## Related documents

- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)
- [2026-03-27-assertion-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-assertion-taxonomy-spec.md)

## Status

`READY_FOR_BOOTSTRAP_IMPLEMENTATION`
