# Assertion Taxonomy Spec

Last updated: 2026-03-27 America/New_York

## Goal

Define the semantic assertion model used by the analysis layer between chunking and world-model updates.

This spec should answer:

- what an assertion is
- how assertions differ from chunks and evidence
- which assertion types exist in v1
- which fields must be extracted
- how lifecycle and authority attach to assertions
- how assertions should be handed off to node and edge resolution

## Conceptual model

The analysis stack should separate:

- `analysis_chunk`
  - a local processing boundary

- `evidence_unit`
  - a concrete source-backed snippet, fact span, or structured support item

- `assertion`
  - a semantic claim derived from one or more evidence units within a chunk

A chunk is not itself an assertion.

An assertion is the smallest unit that should later:

- map into one or more `world_node`s
- propose or reinforce one or more `world_edge`s
- be evaluated for lifecycle state and authority

## Design principles

- preserve source meaning rather than over-compressing it
- separate observation from interpretation where feasible
- preserve conditions, qualifiers, and uncertainty
- store one assertion per semantic claim, not one paragraph per row
- prefer multiple linked assertions to one omnibus assertion
- do not force certainty when the source is ambiguous
- emit `open_question` assertions when the passage is probing rather than claiming

## Assertion scope

Each assertion must be:

- scoped to one `source_document`
- sourced from one primary `analysis_chunk`
- linked to one or more `evidence_unit`s
- time-stamped by document date and, when possible, claim horizon

An assertion may later connect to:

- one `world_node`
- multiple `world_node`s
- one proposed `world_edge`
- multiple proposed `world_edge`s

## Recommended v1 assertion taxonomy

Use a closed `assertion_type` enum in v1.

Recommended values:

- `observation`
- `interpretation`
- `forecast`
- `causal_claim`
- `market_impact`
- `policy_claim`
- `trade_claim`
- `risk_condition`
- `comparative_view`
- `open_question`

### `observation`

Use for source-grounded descriptions of something asserted as currently true or recently true.

Examples:

- CPI came in firmer than expected
- auction demand was weak
- dealer positioning is short duration

Typical properties:

- highest fidelity to source text
- often anchored to a time reference or realized data
- should not quietly bundle downstream implications

### `interpretation`

Use for explanatory framing layered onto an observation.

Examples:

- the CPI surprise suggests underlying services inflation remains sticky
- the auction weakness reflects supply fatigue rather than growth optimism

Typical properties:

- source interpretation of what an observation means
- should remain distinct from policy or market forecast if possible

### `forecast`

Use for forward-looking expectations about macro, policy, markets, or events.

Examples:

- June cuts are less likely
- term premium should remain elevated into Q2
- core inflation should moderate in the second half

Typical properties:

- requires horizon if available
- should preserve conditions when present
- is subject to time decay if not reinforced

### `causal_claim`

Use for explicit or strongly implied cause-effect reasoning.

Examples:

- sticky inflation delays cuts
- higher issuance raises term premium
- weaker growth supports front-end rallying

Typical properties:

- should identify a directional relationship
- should later become a candidate `world_edge`

### `market_impact`

Use for claims about expected or observed effects on prices, spreads, curves, vol, flows, or positioning.

Examples:

- front-end yields should fall
- the dollar should strengthen
- credit spreads may widen

Typical properties:

- often linked to one or more instruments
- may be observational or forecast-like, but should still be preserved as market impact

### `policy_claim`

Use for claims about policy stance, reaction function, constraints, or path.

Examples:

- the Fed remains cautious
- the ECB reaction function is becoming more symmetric
- Treasury supply policy is a key steepening risk

Typical properties:

- may overlap with forecasts
- retain this type when policy is the conceptual center of gravity

### `trade_claim`

Use for explicit investment or trade expressions.

Examples:

- prefer 2s10s steepeners
- remain long USDJPY
- fade breakeven widening at these levels

Typical properties:

- should preserve side, structure, and instrument where possible
- should link to a supporting rationale assertion when available

### `risk_condition`

Use for invalidation logic, scenario branching, or contingent outcomes.

Examples:

- if payrolls weaken materially, the hawkish repricing fades
- upside inflation risk would challenge the bullish duration view

Typical properties:

- condition should be explicit
- useful for later contradiction and invalidation logic

### `comparative_view`

Use for contrastive statements between assets, regions, scenarios, or timing buckets.

Examples:

- US disinflation looks less advanced than euro area disinflation
- the belly is richer than the long end on this framework

Typical properties:

- useful when relative judgment is the main payload
- should not be collapsed into plain forecast or interpretation

### `open_question`

Use when the source or the analysis layer surfaces a real unresolved question rather than a stable claim.

Examples:

- is the market underpricing the persistence of supply pressure
- does weaker activity still translate into front-end rallies in this regime

Typical properties:

- should not be used as a fallback for weak extraction
- should represent uncertainty worth preserving for future evidence accumulation

## Assertion structure

Each assertion should carry:

- `assertion_id`
- `research_id`
- `chunk_id`
- `assertion_order`
- `assertion_type`
- `text`
- `normalized_text`
- `summary_text`
- `polarity`
- `confidence_label`
- `time_horizon`
- `time_anchor`
- `condition_text`
- `qualifier_text`
- `status`
- `authority_band`

Also recommended:

- `subject_nodes`
- `object_nodes`
- `instrument_refs`
- `entity_refs`
- `geography_refs`
- `evidence_unit_ids`
- `parser_theme_ids`
- `source_date`

## Semantic extraction rules

### Rule 1: split compound claims

This sentence should not become one assertion if it contains multiple claim types:

- “CPI surprised to the upside, which keeps the Fed cautious and should pressure the long end”

Preferred extraction:

- `observation`: CPI surprised to the upside
- `policy_claim`: the Fed remains cautious
- `market_impact`: the long end faces pressure

### Rule 2: preserve causal bridges

If a causal bridge is explicit, preserve it as a `causal_claim` in addition to the derived claims.

Preferred extraction:

- `causal_claim`: upside CPI delays Fed easing

### Rule 3: preserve conditions

Conditionals belong in structured fields, not only free text.

Examples:

- `condition_text = "if inflation remains sticky"`
- `condition_text = "unless growth data softens materially"`

### Rule 4: preserve uncertainty language

Do not normalize away phrases such as:

- may
- likely
- increasingly likely
- low conviction
- high confidence

These should influence extraction confidence and downstream authority scoring.

### Rule 5: allow zero assertions

Not every chunk must produce assertions.

`methodology_context` and low-signal `misc_context` chunks may produce none.

## Field normalization guidance

### `normalized_text`

Should be a cleaner but faithful version of the source claim.

Goals:

- remove source-specific verbal clutter
- preserve causal and temporal meaning
- standardize obvious asset/entity naming where safe

### `summary_text`

Should be shorter than `normalized_text` and optimized for retrieval or UI display.

### `polarity`

Recommended values:

- `positive`
- `negative`
- `neutral`
- `mixed`
- `not_applicable`

Apply relative to the assertion’s own subject, not portfolio desirability.

### `confidence_label`

Recommended values:

- `low`
- `medium`
- `high`
- `explicit_high`

Use `explicit_high` when the source itself signals strong conviction.

### `time_horizon`

Recommended values:

- `immediate`
- `near_term`
- `medium_term`
- `long_term`
- `structural`
- `event_bound`
- `unknown`

## Lifecycle model on assertions

Assertions should carry the same two-axis model used elsewhere:

- `status`
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

Important distinction:

- `status` answers what the current evidence posture is
- `authority_band` answers how mature and trusted the assertion has become in the model

## Initial extraction confidence

The extractor should assign an extraction confidence independent of downstream world-model authority.

Recommended `extraction_confidence` values:

- `low`
- `medium`
- `high`

This is useful because:

- a source may be highly confident while extraction may still be ambiguous
- a low-confidence extraction should not be promoted aggressively in graph updates

## Hand-off contract to node and edge resolution

Each extracted assertion should be able to answer:

- what is the primary subject
- what is being said about it
- whether another subject/object is involved
- whether this proposes a relationship
- whether this is forward-looking, observational, or conditional

Suggested logical hand-off:

```json
{
  "assertion_id": "uuid",
  "assertion_type": "causal_claim",
  "normalized_text": "Sticky inflation delays Fed easing.",
  "subjects": ["inflation persistence"],
  "objects": ["Fed easing path"],
  "relation_hint": "drives",
  "time_horizon": "near_term",
  "condition_text": null,
  "confidence_label": "high",
  "extraction_confidence": "high",
  "evidence_unit_ids": ["uuid-1", "uuid-2"]
}
```

## Failure modes to avoid

- one assertion storing an entire paragraph
- collapsing observations and forecasts into one row
- losing conditionals during normalization
- extracting trade recommendations without preserving instrument or side
- using `open_question` as a garbage bucket
- assigning high downstream authority to low-confidence extractions

## Acceptance criteria

This spec is ready for implementation when:

- multi-claim chunks can be split into several assertions cleanly
- the taxonomy covers most common sell-side research claim types
- conditions and horizons survive extraction
- graph resolution can consume assertions without reparsing raw text

## Related documents

- [2026-03-26-analysis-layer-implementation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-layer-implementation-plan.md)
- [2026-03-26-analysis-chunk-taxonomy-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-26-analysis-chunk-taxonomy-spec.md)

## Status

`READY_FOR_AGENT_IMPLEMENTATION`
