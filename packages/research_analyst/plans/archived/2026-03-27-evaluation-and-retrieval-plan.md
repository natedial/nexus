# Evaluation And Retrieval Plan

Last updated: 2026-03-27 America/New_York

## Goal

Define how to evaluate whether the analysis layer is useful and how downstream systems should retrieve value from it.

This spec covers:

- evaluation loops
- manual review methodology
- quality metrics
- failure inspection
- retrieval patterns for synthesis and analyst workflows

## Product success criteria

The analysis layer is successful if it improves:

- synthesis quality
- signal distillation
- traceability of reasoning
- analyst confidence in cross-document connections
- retrieval of relevant supporting and contradictory evidence

It is not successful merely because it stores a large graph.

## Evaluation philosophy

Use mixed evaluation:

- structural correctness
- provenance quality
- practical usefulness to synthesis
- analyst judgment on relevance and trust

Do not optimize only for:

- node count
- edge count
- concept merge rate

## Review surfaces

The system should support review at four levels:

- document analysis review
  - chunk boundaries and assertion extraction

- concept resolution review
  - whether assertions map to the right nodes

- relationship review
  - whether edges are directionally and semantically right

- synthesis retrieval review
  - whether downstream prompts receive better, more useful structure

## Core quality dimensions

### Chunk quality

Questions:

- were major topic switches split correctly
- were causal chains kept intact
- were trade and risk sections isolated appropriately

### Assertion quality

Questions:

- did the extracted claims preserve source meaning
- were conditions and horizons retained
- were observations separated from interpretations and forecasts

### Provenance quality

Questions:

- can each assertion be traced to evidence units
- can each node and edge be traced to supporting assertions
- are contradictions visible rather than hidden

### Resolution quality

Questions:

- were obviously similar concepts grouped appropriately
- were false merges avoided
- were ambiguous cases left soft rather than collapsed

### Temporal quality

Questions:

- do stale forecasts decay reasonably
- do realized outcomes harden or invalidate views sensibly
- do long-lived ideas gain authority in an intuitive way

### Downstream utility

Questions:

- does synthesis produce clearer through-lines
- are conflicting signals surfaced earlier
- can analysts inspect why a synthesis claim was made

## Suggested manual review sets

Build at least three curated review sets:

- `multi_topic_notes`
  - documents covering several markets/assets

- `forecast_to_realization_cases`
  - documents where later evidence can validate or contest the view

- `concept_collision_cases`
  - documents with similar labels that may or may not be the same idea

Recommended starting size:

- 25 to 50 documents total

## Recommended review workflow

1. show document text or excerpt context
2. show chunk boundaries
3. show extracted assertions
4. show proposed node matches
5. show proposed or reinforced edges
6. show lifecycle and authority changes
7. collect reviewer judgment

Review labels should include:

- `correct`
- `acceptable`
- `incorrect`
- `unclear`

## Metrics to track

### Structural metrics

- chunks per document
- assertions per chunk
- evidence units per assertion
- nodes touched per document
- edges touched per document

### Quality metrics

- false split rate
- false merge rate
- assertion preservation rate
- provenance completeness rate
- open-question usefulness rate

### World-model metrics

- new nodes created per day
- existing nodes reinforced per day
- edges moving from `trace` to `path` or `road`
- contested edge rate
- stale forecast rate
- realized validation rate

### Downstream metrics

- synthesis reviewer preference versus baseline
- number of source-backed supporting and contradictory citations surfaced
- reduction in duplicated or redundant synthesis themes
- analyst-rated usefulness of retrieved context

## Retrieval patterns

The analysis layer should support at least these query modes.

### Synthesis context retrieval

Purpose:

- provide prompt-ready inputs to `research_dispatcher`

Retrieval filters:

- recent assertions
- high-authority nodes
- contested edges worth surfacing
- supporting and contradictory evidence by concept

Example output shape:

- concept summary
- latest supporting assertions
- latest contradictory assertions
- relevant open questions

### Concept timeline retrieval

Purpose:

- show how a concept evolved through time

Useful for:

- “sticky inflation”
- “term premium repricing”
- “Treasury supply pressure”

Expected output:

- first seen
- major supporting events
- major contradictory events
- current status and authority

### Event impact retrieval

Purpose:

- show which market impacts or follow-on concepts connect to an event

Useful for:

- FOMC meeting
- CPI release
- Treasury refunding

Expected output:

- immediate impacts
- repeated impacts
- contested impacts

### Analyst QA retrieval

Purpose:

- audit why a synthesis claim or relationship exists

Expected output:

- underlying assertions
- evidence units
- source diversity summary
- lifecycle history

## Recommended evaluation cadence

- weekly manual review during early development
- monthly broader corpus review once cron operation is stable
- targeted review after any resolver or authority-scoring change

## Release gates

Do not expose graph-derived retrieval to downstream synthesis by default until:

- chunk extraction is judged acceptable on the review set
- assertion preservation is strong enough to trust
- provenance coverage is near-complete
- false merge rate is tolerable
- at least one synthesis comparison shows net value over baseline

## Baseline comparisons

Compare against:

- current dispatcher synthesis using raw themes/trades only
- document-local-only enrichment
- graph-assisted retrieval with recent evidence only
- graph-assisted retrieval with authority-aware evidence

This helps answer:

- whether the graph is actually helping
- whether authority and temporal logic add signal or just complexity

## Review harness recommendation

Build a review harness that can show, for one document or concept:

- source text / excerpts
- chunk boundaries
- assertions
- resolved nodes and edges
- lifecycle changes
- retrieval payload preview

This harness is likely more valuable early than any dashboard.

## Acceptance criteria

This evaluation plan is sufficient when:

- another agent can build review tooling from it
- the team can distinguish structural quality from downstream usefulness
- the project has clear release gates before feeding graph outputs into synthesis

## Related documents

- [2026-03-27-world-model-resolution-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-world-model-resolution-spec.md)
- [2026-03-27-assertion-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-assertion-taxonomy-spec.md)
- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)

## Status

`READY_FOR_AGENT_IMPLEMENTATION`
