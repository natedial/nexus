# Analysis Chunk Taxonomy Spec

Last updated: 2026-03-26 America/New_York

## Goal

Define a chunk taxonomy for the analysis layer so that:

- one source document can be split into multiple coherent analysis units
- chunking preserves argument and topic boundaries better than fixed-size windows
- assertions are extracted from chunks rather than from the document as a whole
- downstream graph/world-model updates can carry precise provenance

This spec is intended as a handoff document for implementation work in this repo.

## Why chunks exist

The analysis layer should not treat a research note as one atomic thought.

Many documents contain:

- multiple markets
- multiple assets
- several forecasts with different horizons
- both observations and interpretations
- several causal chains inside one note

A chunk is the processing boundary.

An assertion is the semantic unit.

The relationship should be:

- one `source_document`
- many `analysis_chunk`
- many `evidence_unit`
- many `assertion`

## Design principles

- chunk by topical and argumentative coherence, not token count
- prefer stable, explainable chunk boundaries over aggressive splitting
- preserve source order
- allow a chunk to yield multiple assertions
- allow one assertion to cite multiple evidence units within the same chunk
- avoid merging unrelated topics into one chunk just because they share a section
- avoid splitting one causal chain across multiple chunks unless the document clearly does

## Recommended chunk taxonomy

V1 should support a controlled chunk taxonomy with one primary type per chunk.

Recommended `chunk_type` values:

- `thesis_summary`
- `macro_view`
- `market_view`
- `asset_view`
- `event_analysis`
- `data_interpretation`
- `forecast_block`
- `trade_rationale`
- `risk_scenario`
- `positioning_flow`
- `policy_view`
- `cross_asset_linkage`
- `methodology_context`
- `misc_context`

### `thesis_summary`

Use for:

- executive summary
- key takeaways
- bottom line
- opening thesis paragraphs

Typical characteristics:

- broad synthesis
- compressed high-signal claims
- often spans multiple subtopics

Guidance:

- split further if the summary clearly separates into distinct macro, rates, FX, or credit blocks

### `macro_view`

Use for:

- growth
- inflation
- labor
- macro cycle
- recession or soft-landing framing

Typical assertions:

- economic state descriptions
- causal macro narratives
- broad regime interpretations

### `market_view`

Use for:

- broad market interpretation not yet narrowed to one asset
- discussion of market pricing, sentiment, technicals, or regime conditions

Examples:

- risk appetite
- volatility regime
- liquidity backdrop
- valuation regime

### `asset_view`

Use for:

- one asset class or sub-market with a coherent local argument

Examples:

- UST front end
- 10y term premium
- EURUSD
- IG credit spreads
- crude curve

Guidance:

- create separate chunks when the note switches from one asset or market to another

### `event_analysis`

Use for:

- central bank meetings
- elections
- tariff announcements
- Treasury refunding
- fiscal packages
- geopolitical events

Typical assertions:

- event significance
- event transmission channels
- event-conditioned scenarios

### `data_interpretation`

Use for:

- CPI, payrolls, GDP, PMIs, retail sales, auctions, earnings, inventory data

Typical assertions:

- observed print/result
- interpretation of surprise
- inferred implications for policy or markets

Guidance:

- keep observation and interpretation in the same chunk if tightly coupled
- split them only if the note clearly separates “what happened” from “what it means”

### `forecast_block`

Use for:

- explicit outlooks
- path forecasts
- target levels
- scenario-based forward views

Typical assertions:

- expected policy path
- expected yield, spread, FX, or commodity moves
- timing and horizon statements

### `trade_rationale`

Use for:

- explicit trade recommendations
- entry/exit reasoning
- catalyst paths
- risk/reward framing

Guidance:

- if the trade rationale relies on a separate broad thesis chunk, link them later through assertions rather than forcing them into one chunk

### `risk_scenario`

Use for:

- upside/downside cases
- tail risks
- what-could-break-the-view sections

Typical assertions:

- invalidation conditions
- scenario branching
- contingent impact paths

### `positioning_flow`

Use for:

- client positioning
- fund flows
- dealer balance sheet dynamics
- technical positioning

Typical assertions:

- current positioning state
- likely unwind or squeeze dynamics
- non-fundamental market pressure

### `policy_view`

Use for:

- central bank reaction function
- fiscal stance
- regulatory posture
- supply policy or issuance policy

Typical assertions:

- likely policy response
- policy constraints
- policy transmission into growth, inflation, or markets

### `cross_asset_linkage`

Use for:

- explicit multi-market chains in one local argument

Examples:

- inflation surprise -> front-end repricing -> USD strength -> EM pressure
- oil shock -> inflation expectations -> breakevens -> real yields

Guidance:

- use when the cross-market linkage is the actual point of the passage
- do not use just because two assets are mentioned casually

### `methodology_context`

Use for:

- model descriptions
- decomposition methodology
- survey construction
- data-cleaning notes

Guidance:

- usually lower priority for assertion extraction
- keep when needed for confidence or evidence interpretation

### `misc_context`

Use for:

- low-priority contextual passages that do not fit another type

Guidance:

- should be uncommon
- prefer a specific type whenever possible

## Secondary chunk tags

In addition to `chunk_type`, attach zero or more secondary tags.

Recommended tag families:

- `asset_class`
  - `rates`
  - `fx`
  - `equities`
  - `credit`
  - `commodities`
  - `cross_asset`

- `topic`
  - `inflation`
  - `growth`
  - `labor`
  - `policy`
  - `fiscal`
  - `supply`
  - `positioning`
  - `volatility`
  - `liquidity`

- `horizon`
  - `spot`
  - `near_term`
  - `medium_term`
  - `structural`

- `geography`
  - free-text normalized set such as `US`, `Euro area`, `Japan`, `China`, `EM`

- `entity`
  - normalized mentions such as `Fed`, `ECB`, `Treasury`, `BOJ`

These tags help retrieval and synthesis without replacing the primary chunk type.

## Boundary rules

Chunk boundaries should follow these rules in order.

### Rule 1: Respect explicit structure

Prefer boundaries at:

- section headers
- subsection headers
- bullet block titles
- “bottom line”, “implications”, “trade idea”, or “risks” labels

### Rule 2: Split on major topic switches

Create a new chunk when the note clearly shifts:

- from macro to asset-specific discussion
- from one asset class to another
- from observation to trade recommendation
- from baseline view to risk scenario

### Rule 3: Keep one local causal chain together

Do not split passages that form one coherent causal chain unless the author clearly does.

Examples:

- “higher tariffs raise goods inflation, which delays cuts, which supports the dollar”
- “weak payrolls steepen the odds of front-end rallying and flatten recession pricing”

### Rule 4: Avoid giant omnibus chunks

If a summary or section contains multiple independent arguments, split it into separate chunks even if they appear under one header.

### Rule 5: Prefer under-merging to over-merging

When uncertain, it is safer to create two adjacent chunks than one overly broad chunk.

The graph can reconnect related assertions later.

## Assertion extraction rules

Assertions should be extracted from chunks, not directly from the full document.

Each chunk may produce:

- zero assertions
- one primary assertion
- several linked assertions
- one or more open questions if ambiguity is high

Recommended `assertion_type` values for v1:

- `observation`
- `interpretation`
- `forecast`
- `causal_claim`
- `market_impact`
- `policy_claim`
- `trade_claim`
- `risk_condition`
- `open_question`

Recommended extraction posture:

- separate observations from interpretations when possible
- separate forecasts from supporting causal logic when possible
- preserve qualifiers and conditions
- do not force a claim if the chunk is mostly context or methodology

## Example chunking

Example source passage:

1. “February CPI came in firmer than expected.”
2. “That keeps the Fed cautious and makes a June cut less likely.”
3. “As a result, we expect 10y term premium to remain elevated.”
4. “We still prefer 2s10s steepeners as supply pressure builds.”

Recommended extraction:

- chunk A
  - `chunk_type = data_interpretation`
  - assertions:
    - observation: CPI was firmer than expected
    - interpretation: firmer CPI keeps the Fed cautious

- chunk B
  - `chunk_type = forecast_block`
  - assertions:
    - forecast: June cut is less likely
    - market_impact: 10y term premium remains elevated

- chunk C
  - `chunk_type = trade_rationale`
  - assertions:
    - trade_claim: prefer 2s10s steepeners
    - causal_claim: supply pressure supports the trade

## Minimal data contract

Suggested logical shape for an `analysis_chunk`:

```json
{
  "chunk_id": "uuid",
  "research_id": 12345,
  "chunk_order": 3,
  "chunk_type": "forecast_block",
  "section_name": "Rates outlook",
  "title": "Higher term premium into Q2",
  "text": "...",
  "topic_tags": ["rates", "policy", "inflation"],
  "entity_tags": ["Fed", "UST"],
  "horizon_tag": "near_term",
  "source_span": {
    "page_start": 3,
    "page_end": 4,
    "paragraph_start": 10,
    "paragraph_end": 13
  }
}
```

Suggested logical shape for extracted assertions:

```json
{
  "assertion_id": "uuid",
  "chunk_id": "uuid",
  "research_id": 12345,
  "assertion_type": "forecast",
  "text": "June cuts are less likely after the CPI surprise.",
  "qualifiers": ["conditional on continued inflation firmness"],
  "time_horizon": "near_term",
  "evidence_unit_ids": ["uuid-1", "uuid-2"]
}
```

## Implementation recommendation

V1 should use a hybrid chunking pipeline:

1. parser structure hints
   - headers
   - theme order
   - excerpt grouping

2. deterministic splitting rules
   - section boundaries
   - topic shifts
   - trade/risk markers

3. optional LLM cleanup pass only if needed
   - merge oversplit chunks
   - relabel ambiguous chunk types

Opinionated recommendation:

- start deterministic
- make chunk boundaries auditable
- add LLM-assisted cleanup only after reviewing real parser output

## Failure modes to avoid

- one huge chunk for a multi-topic note
- fixed-size chunks that split one argument in half
- trade rationale merged into broad macro discussion
- observation and implication collapsed without distinction
- asset-specific discussion mislabeled as general macro
- summary pages treated as one universal chunk despite multiple independent claims

## Acceptance criteria

This taxonomy is good enough for implementation when:

- a single multi-topic note can be split into coherent local analysis units
- most chunks map cleanly to one primary `chunk_type`
- chunks preserve provenance and source order
- assertion extraction can operate chunk-by-chunk without needing the entire note each time
- trade rationales, risks, forecasts, and data interpretations are separable in common bank research formats
- ambiguous content can fall back to `misc_context` without breaking the pipeline

## Recommended next implementation tasks

1. inspect real parsed documents and collect 20-30 representative note structures
2. test the taxonomy against those samples manually
3. define the concrete `analysis_chunk` persistence schema
4. define deterministic chunk boundary heuristics
5. define assertion extraction prompts or rules by `chunk_type`
6. measure chunk-count distribution per note
7. add a review harness that shows document text, chunk boundaries, and extracted assertions side by side

## Status

`READY_FOR_AGENT_IMPLEMENTATION`
