# Theme Link Enrichment Spec

Last updated: 2026-03-24 America/New_York

## Goal

Define a dedicated enrichment stage between:

1. `research_parser`
2. theme-link enrichment
3. `research_dispatcher`

This stage should own generation of `research_theme_links` without pushing that responsibility into single-document parsing or into the final report-generation path.

## Product Intent

The purpose of theme links is to add structure on top of already-normalized themes so downstream systems can later answer questions such as:

- which themes in one document reinforce the same thesis
- which themes are causal drivers versus consequences
- which themes contradict or qualify one another
- which local relationships are worth surfacing in synthesis, QA, or analyst review

Confirmed recommendation:

- the first consumer is synthesis quality in the analyst middle step
- internal QA is the secondary consumer
- v1 should only solve document-local structure
- v1 should improve machine readability and future report quality, not create a user-facing graph product yet
- do not design v1 around a user-facing graph or curation UI
- `research_dispatcher` should ignore links until a concrete reporting use case is agreed

Do not start with cross-document theme graphs. The current table shape and parser output support document-scoped links; cross-document ontology work is a different problem.

## Proposed Service

Build a separate service or scheduled job called `research_theme_linker`.

It should:

- select documents whose normalized themes are complete
- load one document at a time
- infer relationships among that document's themes
- replace all existing `research_theme_links` rows for that document
- track run state, version, and errors in a separate linker-owned table

## System Boundary

### `research_parser` owns

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`
- top-level document metadata columns
- `document_hash`, `theme_count`, `trade_count`

### `research_theme_linker` owns

- deciding when a document is ready for link inference
- reading normalized themes and excerpts
- inferring theme-to-theme relationships for a single document
- writing `research_theme_links`
- tracking link-generation status, version, and errors

### `research_dispatcher` owns

- consuming enriched data for reporting and synthesis
- ignoring links until it has a defined product use
- never being responsible for generating or persisting `research_theme_links`

## V1 Scope

V1 should support:

- document-local related-theme inference
- idempotent reruns
- batch processing of newly normalized documents
- manual or scheduled backfill of older normalized documents
- deterministic rules only
- a high-precision operating posture, even if that means lower recall

V1 should not support:

- cross-document graph edges
- a global topic ontology
- user-facing link editing or review UI
- parser-time link extraction
- automatic downstream behavior changes in `research_dispatcher`
- mandatory LLM adjudication

## Expected Data Characteristics

This spec assumes the source documents are sell-side bank research PDFs already parsed into normalized themes and excerpts. Based on the adjacent plans, each `parsed_research` row represents one document and each document has a bounded number of themes.

Working assumptions for v1:

- theme counts per document are usually single-digit to low-teens, with occasional higher outliers
- pairwise within a document is still computationally cheap at that scale
- theme labels are human-readable but not guaranteed to be globally stable
- excerpts are short evidence spans, not full-document text
- `argument_structure` is a bonus signal, not primary truth
- excerpts are useful evidence but not canonical truth and may include parser noise or truncation

If any of those assumptions are false in production data, the linker strategy should be adjusted before implementation.

## Why This Stage Exists

Putting theme links in the parser is the wrong boundary because parsing should stay focused on extracting stable document facts.

Putting theme links in `research_dispatcher` is also the wrong default because dispatcher is currently a read/report/send workflow, not a durable enrichment writer.

The missing middle stage creates a cleaner pipeline:

- parser writes normalized facts
- linker adds higher-order document structure
- dispatcher consumes enriched structure only when product logic is ready

## Data Dependencies

The linker depends on these fields being present and trustworthy:

- `parsed_research.id`
- `parsed_research.document_hash`
- `parsed_research.theme_count`
- `research_themes` rows for that `research_id`
- `research_theme_excerpts` rows for those theme ids

Useful optional inputs:

- `research_themes.relevance`
- `research_themes.classification`
- `research_themes.strength`
- `research_themes.confidence`
- `research_themes.directionality`
- `research_themes.argument_structure`
- `research_themes.context`

Relevant parser references:

- [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py)
- [src/extraction/models.py](/Users/ncdial/devwork/research_parser/src/extraction/models.py)

## Readiness Rule

A document is eligible for link inference only when:

1. `document_hash IS NOT NULL`
2. `theme_count > 0`
3. `count(research_themes.id) = parsed_research.theme_count`

If those conditions are not met:

- skip the document
- do not write link rows
- leave it for a later pass

This mirrors the mixed-mode safety rule already identified for dispatcher.

## Link Taxonomy

V1 should use a small controlled enum for `research_theme_links.relationship`.

Recommended values:

- `reinforces`
- `depends_on`
- `contradicts`
- `qualifies`
- `drives`

Definitions:

- `reinforces`: both themes support the same underlying point
- `depends_on`: theme A relies on theme B being true
- `contradicts`: one theme weakens, offsets, or conflicts with the other
- `qualifies`: one theme narrows, scopes, or conditions the other
- `drives`: theme A is presented as a causal driver of theme B

Opinionated recommendation:

- keep the enum closed in v1
- avoid an open-ended relationship vocabulary
- put nuance in `explanation`, not in enum sprawl

## Link Direction Rules

The current table shape implies directed rows, so direction must be explicit.

Recommended orientation:

- `A depends_on B`: store `from_theme_id = A`, `to_theme_id = B`
- `A drives B`: store `from_theme_id = A`, `to_theme_id = B`
- `A qualifies B`: store `from_theme_id = A`, `to_theme_id = B`

For symmetric relationships:

- `reinforces`
- `contradicts`

Store exactly one row per unordered pair using canonical ordering:

- smaller `theme_id` in `from_theme_id`
- larger `theme_id` in `to_theme_id`

Invariants:

- no self-links
- no duplicate rows for the same `(research_id, from_theme_id, to_theme_id, relationship)`
- exactly one relationship row per pair in v1
- `explanation` should be short and human-readable

## Input Contract For The Linker

Per document:

```json
{
  "research_id": 12345,
  "document_hash": "sha256...",
  "document_name": "2026-03-22_JPM_....pdf",
  "source": "JPMorgan",
  "source_date": "2026-03-22",
  "themes": [
    {
      "theme_id": 9001,
      "theme_order": 1,
      "label": "Higher term premium",
      "relevance": ["Rates"],
      "classification": "Forecast",
      "strength": "Primary",
      "confidence": "High",
      "context": "The note argues that...",
      "directionality": {"bearish_rates": 2},
      "argument_structure": {
        "conditionals": ["If inflation remains sticky"],
        "confidence_basis": "Positioning and term premium decomposition",
        "dependencies": ["Sticky inflation"],
        "contradictions": []
      },
      "excerpts": [
        "Investors should expect term premium to rise..."
      ]
    }
  ]
}
```

Hydration rules:

- preserve theme order from parser output
- keep excerpt ordering stable where possible
- do not require raw full-document text for v1

## Output Contract For The Linker

Per document:

```json
{
  "research_id": 12345,
  "document_hash": "sha256...",
  "linker_version": "v1",
  "links": [
    {
      "from_theme_id": 9001,
      "to_theme_id": 9002,
      "relationship": "drives",
      "explanation": "Sticky inflation is presented as the reason term premium rises."
    }
  ]
}
```

If no valid relationships are found:

- write zero link rows
- still mark the document run as successful

## Proposed Schema Additions

The existing `research_theme_links` table is close to sufficient for storing v1 links, but it still needs v1 constraint tightening plus linker-owned run control.

### Keep

- `research_theme_links`

### Add

```sql
ALTER TABLE research_theme_links
    ADD CONSTRAINT uq_research_theme_links_research_from_to
    UNIQUE (research_id, from_theme_id, to_theme_id);

CREATE TABLE research_theme_link_runs (
    research_id BIGINT PRIMARY KEY REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    linker_version TEXT NOT NULL,
    status TEXT NOT NULL,
    theme_count INTEGER NOT NULL DEFAULT 0,
    candidate_pair_count INTEGER NOT NULL DEFAULT 0,
    llm_pair_count INTEGER NOT NULL DEFAULT 0,
    link_count INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_text TEXT NULL
);

CREATE INDEX idx_research_theme_link_runs_status
    ON research_theme_link_runs(status);

CREATE INDEX idx_research_theme_link_runs_hash_version
    ON research_theme_link_runs(document_hash, linker_version);
```

Recommended `status` values:

- `success`
- `skipped_not_ready`
- `error`

Why a separate run table:

- do not overload `parsed_research` with enrichment-specific status
- allow versioned reruns
- allow stale-output detection when logic changes
- keep parser and linker ownership separated
- provide basic operational metrics without querying link rows directly

Why tighten `research_theme_links` in v1:

- the existing schema prevents self-links, but does not prevent duplicate pairs
- v1 allows exactly one stored relationship row per theme pair
- the application should still validate canonical ordering and same-document ownership before writing

## Selection Logic

The linker should select documents where:

- normalized themes are complete
- and no link run exists
- or stored `document_hash` differs
- or stored `linker_version` differs
- or prior run status is `error`

That gives:

- idempotency
- rerun support when logic changes
- automatic pickup when parser or backfill updates a document

Recommended selection order:

- oldest unprocessed first for backfills
- newest first for steady-state cron runs

## Inference Strategy

Use a hybrid pipeline:

1. deterministic candidate generation
2. deterministic shortcut rules
3. no LLM adjudication in v1

### Step 1: Candidate generation

For a single document:

- fetch all normalized themes
- generate all unordered theme pairs
- exclude self-pairs
- evaluate all pairs unless theme counts become unexpectedly large

Rationale:

- pairwise evaluation is simple and auditable
- the per-document search space should be small enough for v1

### Step 2: Deterministic shortcut rules

Infer links without an LLM when structured evidence is strong.

Examples:

- `argument_structure.dependencies` mentioning another theme label
  - emit `depends_on`
- `argument_structure.contradictions` mentioning another theme label
  - emit `contradicts`
- strong lexical overlap plus same directionality and same relevance
  - emit `reinforces`
- explicit causal wording in one theme context or excerpt
  - emit `drives`
- conditional language that clearly scopes another theme
  - emit `qualifies`

Opinionated recommendation:

- deterministic rules should win when confidence is high
- keep rule logic inspectable and testable
- avoid opaque scoring systems in v1
- when evidence is weak or ambiguous, emit no link

### Future option: LLM adjudication

LLM adjudication is intentionally out of scope for v1.

Add it only if:

- a manually reviewed sample shows deterministic rules are clearly insufficient
- the incremental quality gain justifies cost and operational complexity
- prompts can be constrained tightly enough to preserve the high-precision posture

If LLM adjudication is introduced later:

- send only unresolved candidate pairs
- use temperature `0`
- require structured JSON with one enum relationship or `none`
- keep explanation grounded in the provided pair evidence

## Write Strategy

For each eligible document:

1. fetch themes and excerpts
2. infer links
3. start a database transaction
4. delete existing `research_theme_links` rows for that `research_id`
5. insert the new set
6. upsert a row in `research_theme_link_runs`
7. commit

If inference fails:

- do not write partial link rows
- upsert `research_theme_link_runs.status = 'error'`
- record the failure text

Opinionated recommendation:

- treat per-document writes as replace-all
- make the document the unit of atomicity
- prefer no links over partially persisted links

## Concurrency and Idempotency

V1 can assume a single batch worker. If that changes later, add one of:

- row-level claim logic in `research_theme_link_runs`
- Postgres advisory locking keyed by `research_id`

Idempotency rule:

- if the same document hash and linker version are processed twice, the final stored rows must be identical

## Workflow

### End-to-end data flow

1. `research_parser`
   - parses PDFs
   - writes `parsed_research`
   - writes `research_themes`
   - writes `research_theme_excerpts`

2. `research_theme_linker`
   - polls for eligible normalized documents
   - infers document-local links
   - writes `research_theme_links`
   - records run state in `research_theme_link_runs`

3. `research_dispatcher`
   - reads documents and normalized themes
   - may read links later when a reporting or synthesis use case exists
   - never computes links in the durable write path

## Deployment Model

### Recommended form

A separate Python 3.11 batch service or scheduled CLI.

Preferred options:

1. cron-triggered batch command
2. long-running poller only if freshness requirements justify it

Opinionated recommendation:

- start with a nightly cron-triggered batch job
- move to a poller only if freshness becomes a real product need

Reason:

- lower operational complexity
- easier to test and backfill
- no queue infrastructure needed on day one

## Proposed Tech Stack

Use the same operational stack family already present in the adjacent systems.

### Core runtime

- Python 3.11
- `supabase-py`
- `pydantic`
- `structlog`
- `tenacity`

### Scheduling

Choose one:

- `cron` for batch CLI
- `APScheduler` if later converted into a long-running service

### Inference

- Python rules first
- optional OpenAI or Anthropic adjudication for ambiguous pairs

### Storage

- Supabase Postgres
- existing normalized theme tables
- existing `research_theme_links`
- new `research_theme_link_runs`

## Proposed Module Layout

If built as its own Python package:

```text
research_theme_linker/
  src/
    main.py
    config.py
    selector.py
    hydrator.py
    linker.py
    rules.py
    llm.py
    writer.py
    models.py
  tests/
    test_rules.py
    test_selector.py
    test_writer.py
    test_end_to_end.py
```

Responsibilities:

- `selector.py`
  - find eligible documents
- `hydrator.py`
  - fetch document, themes, and excerpts into one payload
- `rules.py`
  - deterministic relation heuristics
- `llm.py`
  - constrained pair adjudication
- `linker.py`
  - orchestration and merge of rule-based and LLM outcomes
- `writer.py`
  - replace-all writes plus run-state updates

## Testing Strategy

Minimum test coverage for v1:

1. readiness logic
   - incomplete normalized themes are skipped
2. deterministic rule coverage
   - dependencies, contradictions, qualifiers, and causal wording
3. direction canonicalization
   - symmetric versus asymmetric relationships
4. write-path behavior
   - replace-all writes are atomic per document
5. idempotent reruns
   - same input produces same stored result
6. zero-link success case
   - successful run with no emitted links
7. error handling
   - failed inference records run-state error and no partial links

Do not require live Supabase access for unit tests.

## Rollout Plan

1. Keep the first consumer limited to analyst middle-step reasoning and internal QA.
2. Validate parser data quality on a sample of real sell-side research documents.
3. Add the run-state table.
4. Add the v1 uniqueness constraint on `research_theme_links`.
5. Implement deterministic rules and replace-all writer first.
6. Backfill a small sample and review emitted links manually with a precision-first lens.
7. Keep nightly batch scheduling for v1.
8. Add LLM adjudication only if deterministic coverage is clearly insufficient on reviewed samples.
9. Backfill historical eligible documents.
10. Revisit `research_dispatcher` only when there is a concrete reporting use case.

## Acceptance Criteria

V1 is complete when:

- eligible documents are detected correctly
- incomplete documents are skipped safely
- link rows are persisted deterministically per document
- reruns occur automatically on `document_hash` or `linker_version` change
- failures do not leave partial links behind
- the run table answers which docs succeeded, failed, or were skipped
- at least one manual review pass shows that emitted links are precise enough to justify the stage
- the explanation field is readable by analysts even if it is initially used only for internal/debug workflows

## Resolved Decisions

### Product behavior

- contradictory links should not affect report output in v1
- the first consumer is analyst middle-step reasoning and internal QA
- `research_dispatcher` should continue ignoring links until a concrete reporting use case is agreed

### Data validation posture

- measure the observed `theme_count` distribution before rollout, but do not block prototyping on that measurement
- do not require a labeled gold dataset before implementation starts
- do require at least one analyst-reviewed sample pass before rollout to judge precision
- treat theme labels as weak signals rather than stable identifiers across sources or parser prompt versions
- rely more on excerpts, context, and `argument_structure` than on exact label matching

### Operational and schema decisions

- the linker should be format-agnostic and operate on normalized rows, not on PDF-specific assumptions
- under the current parser write path, a new `document_hash` will usually create a new `parsed_research` row rather than mutate an existing row in place
- the current `research_theme_links` schema does not include a uniqueness constraint beyond the no-self-link check
- v1 should enforce exactly one stored relationship row per `(research_id, from_theme_id, to_theme_id)` pair
- same-document theme ownership should be enforced in application logic in v1, with stronger database enforcement considered later if needed

## Follow-up Validation Tasks

- measure the production distribution of `theme_count` to confirm pairwise document-local comparison remains cheap at the high end
- assemble a 25-50 document analyst review sample to evaluate emitted-link precision
- confirm whether stronger database constraints for same-document theme ownership are worth adding after the first implementation pass

## Status

`READY_FOR_IMPLEMENTATION_PENDING_VALIDATION_TASKS`
