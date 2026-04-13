# World Model Resolution And Temporal Update Spec

Last updated: 2026-03-27 America/New_York

## Goal

Define how assertions become durable world-model nodes and edges over time.

This spec covers:

- soft concept resolution
- node and edge creation
- evidence accumulation
- contradiction handling
- forecast decay
- realized-data hardening
- open-question generation

## Design posture

The world model should behave like a cautious analyst memory, not a brittle ontology.

That means:

- allow ambiguity
- preserve competing concepts
- strengthen only with repeated evidence
- reinterpret rather than overwrite when new data arrives
- keep unresolved questions alive when evidence is incomplete

## Resolution layers

The recommended update flow is:

1. extract assertions from document chunks
2. normalize assertion subjects and objects
3. attempt soft match to existing `world_node`s
4. create or reinforce `world_edge`s
5. attach provenance
6. update lifecycle state and authority
7. evaluate temporal effects such as decay, hardening, or invalidation
8. emit `open_question` nodes if uncertainty remains materially unresolved

## Node resolution strategy

Use soft canonicalization first.

That means:

- do not require a new assertion to collapse into one existing node
- allow candidate matches with scores
- create a new node when confidence is insufficient
- preserve aliases and competing labels

### Recommended node-resolution signals

- normalized label similarity
- shared entities
- shared instruments
- shared geography
- shared topic tags
- compatible assertion type and node type
- compatible horizon
- repeated co-occurrence with similar evidence

### Signals to distrust

- superficial lexical overlap with different asset or policy context
- same phrase used across unrelated markets
- one-off semantic similarity without corroborating evidence

## Node creation rules

Create a new `world_node` when:

- no existing candidate passes the confidence threshold
- multiple candidates remain plausibly different concepts
- the assertion introduces a clearly new event, instrument, or question

Seed new nodes with:

- `status = proposed`
- `authority_band = seed`
- `support_count = 1`
- `source_diversity = 1`

## Edge resolution strategy

Edges should be evidence-backed relationships between nodes, not just textual similarity links.

Candidate edge sources:

- `causal_claim`
- `forecast`
- `market_impact`
- `comparative_view`
- `risk_condition`
- `open_question`

### Recommended v1 edge behavior

- create weak edges conservatively
- reinforce repeated edges aggressively when provenance is independent
- preserve contradictions rather than flattening them away

## Edge maturity model

Your “footpaths to roads to highways” framing maps well to an explicit maturity model.

Recommended machine-readable values:

- `trace`
- `path`
- `road`
- `highway`
- `structural`

How it relates to lifecycle:

- maturity is about accumulation and durability
- `status` is about the current posture
- `authority_band` is about overall standing

Example:

- an edge can be `contested + road`
- a new edge can be `supported + trace`

## Evidence accumulation rules

An assertion should reinforce a node or edge when:

- it is not a duplicate contribution from the same provenance
- it adds independent source support
- it matches the conceptual relationship closely enough

Support should be weighted by:

- extraction confidence
- source confidence
- source independence
- evidence specificity
- temporal relevance

Recommended stance:

- multiple notes from one bank should count less than independent agreement across firms
- explicit evidence should count more than vague thematic overlap

## Contradiction handling

Do not model contradiction as deletion.

When a contradictory assertion arrives:

- add contradictory provenance
- increment `contradiction_count`
- consider shifting `status` to `contested`
- preserve prior authority unless contradiction is overwhelming

Examples:

- one note says supply drives term premium higher
- another says growth slowdown will dominate and pull long-end yields lower

These may:

- contest the same edge
- create a new competing edge
- or both

## Forecast decay

Forecasts should lose freshness over time if not reinforced or resolved.

Recommended rule:

- forecasts do not instantly become false when time passes
- they move from `supported` or `reinforced` toward `stale` if the forecast horizon expires without confirming evidence

Suggested inputs:

- source date
- stated horizon
- elapsed time
- arrival of new supporting or contradictory evidence

## Realized-data hardening

Realized observations should be able to harden, reinterpret, or invalidate prior forecasts and causal links.

Examples:

- repeated upside inflation surprises may harden an existing “sticky inflation -> delayed cuts” edge
- weak payrolls may challenge a previously reinforced “Fed stays restrictive through summer” forecast

Recommended effects:

- increase support for matching nodes or edges
- create `realized_as` links between forecast and realized-data nodes
- update `status` for unresolved forecasts that were not borne out

## Temporal reinterpretation

The system should support reinterpretation rather than only binary confirmation/failure.

Examples:

- a forecast may be directionally right but late
- a relationship may hold in one regime but weaken in another
- a concept may survive but its transmission channel changes

Recommended representation:

- keep `world_edge_history`
- track `regime_count`
- store a short `change_reason`

## Open-question generation

The system should prefer questions over forced implications when:

- candidate node matches are ambiguous
- conflicting edges recur without resolution
- a repeated pattern appears but causal direction remains unclear
- the note itself frames the issue as unresolved

Examples:

- “Does supply now dominate growth in long-end pricing?”
- “Is weaker activity still bullish duration under current inflation persistence?”

Recommended behavior:

- create or reinforce an `open_question` node
- link it to relevant concepts and edges
- allow question authority to rise if the question persists as a real uncertainty in the corpus

## Resolution thresholds

Use three operating thresholds:

- `propose`
  - low threshold for creating tentative nodes or edges

- `reinforce`
  - medium threshold for adding support to an existing structure

- `merge`
  - high threshold for treating two concepts as effectively the same in v1

Opinionated recommendation:

- set `merge` very high
- use `related_to` or `same_idea_as` before hard unification

## Suggested status transitions

Examples, not hard rules:

- `proposed -> supported`
  - when a second credible source adds aligned evidence

- `supported -> reinforced`
  - when support becomes repeated and diverse

- `reinforced -> contested`
  - when meaningful contradictory evidence appears

- `supported -> stale`
  - when forecast horizon passes without reinforcement

- `contested -> invalidated`
  - when repeated contradictory realized evidence overwhelms prior support

## Suggested authority evolution

Authority should rise from:

- repeated support
- source diversity
- regime durability
- realized validation
- survival through reinterpretation

Authority should fall slowly from:

- repeated failed validation
- high-quality contradictory evidence
- persistent staleness

Authority should not fall sharply from:

- one contradictory note
- one low-confidence extraction
- mere passage of time without horizon context

## Recommended implementation posture

V1 resolution should be hybrid:

1. deterministic normalization and type gating
2. simple similarity scoring
3. optional constrained LLM adjudication only for ambiguous high-value cases

Do not start with:

- unconstrained ontology generation
- fully automatic deep causal reasoning
- graph-wide inference passes that cannot be audited

## Acceptance criteria

This spec is sufficient when:

- repeated similar assertions can accumulate around shared nodes
- weak evidence produces weak structure rather than overconfident merges
- contradictory evidence is preserved explicitly
- forecasts can decay and realized data can harden or contest relationships
- unresolved ambiguity can surface as `open_question` nodes

## Related documents

- [2026-03-27-assertion-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-assertion-taxonomy-spec.md)
- [2026-03-27-analysis-persistence-schema-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-persistence-schema-spec.md)
- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)

## Status

`READY_FOR_AGENT_IMPLEMENTATION`
