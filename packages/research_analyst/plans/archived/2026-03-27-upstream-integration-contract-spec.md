# Upstream Integration Contract Spec

Last updated: 2026-03-27 America/New_York

## Goal

Define the expected contract between this analysis layer and its upstream systems.

This document is meant to reduce interface ambiguity before code is written against `research_parser` outputs.

Validation follow-up:

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)

Important outcome:

- the original target contract was directionally useful, but the current upstream shape differs materially in one key place: `state.db` is keyed by `file_id`, not `research_id`

## Scope

This contract covers:

- what is expected from parser `state.db`
- what is expected from the parsed database
- which fields are required versus optional
- how the analysis layer should handle missing or partial upstream data

This began as a target contract rather than a verified schema reference.

It should now be read together with the validation results spec, which captures the current verified upstream shape and the places where that shape differs from the original target contract.

## Upstream systems

Two upstream inputs exist:

1. parser `state.db`
   - operational trigger source

2. parsed database
   - authoritative content source

The analysis layer should not require more than this from upstream.

## `state.db` contract

### Purpose

`state.db` is for:

- change detection
- success-state discovery
- candidate selection

It is not for:

- full content hydration
- graph reasoning
- assertion extraction

### Minimum required fields

The analysis layer expects each successful parser output to expose at least:

- `research_id`
- `document_hash`
- `status`
- `completed_at`

Strongly preferred:

- `source`
- `source_date`
- `error_text`
- parser version or job version

### Required semantics

- `status = success` means parsed DB content is expected to be readable
- `research_id` identifies the parsed document row in the authoritative content store
- `document_hash` uniquely identifies the analyzed document version
- `completed_at` is usable as a selection watermark

### Failure handling

If `state.db` shows success but parsed DB hydration fails:

- record an analysis error
- do not advance the item as fully processed
- allow later reconciliation or retry

## Parsed DB contract

### Purpose

The parsed DB is the source of truth for:

- document metadata
- normalized themes
- excerpts
- optional raw content fallback

### Minimum required document fields

For each `research_id`, the analysis layer expects:

- `id`
- `document_hash`
- `source`
- `source_date`
- `theme_count`

Strongly preferred:

- `title`
- `publisher`
- `region`
- `asset_focus`
- `document_link`
- `raw_text` or equivalent fallback content reference

### Minimum required theme fields

For each normalized theme, the analysis layer expects:

- `id`
- `research_id`
- `label`

Strongly preferred:

- `context`
- `relevance`
- `classification`
- `strength`
- `confidence`
- `directionality`
- `argument_structure`
- `theme_order`

### Minimum required excerpt fields

For each excerpt, the analysis layer expects:

- `theme_id`
- `text`

Strongly preferred:

- excerpt ordering
- source span or page reference

## Readiness contract

The analysis layer should consider a document ready only when:

1. `document_hash` is non-null
2. `theme_count > 0`
3. normalized theme count equals `theme_count`

If these conditions fail:

- mark `skipped_not_ready`
- do not attempt graph updates

## Optional raw content contract

Raw content should not be mandatory for v1 if normalized themes and excerpts are good enough.

However, raw content or structured raw spans are strongly preferred for:

- better chunk boundary detection
- recovering context when excerpts are sparse or noisy
- future review tooling

Recommended posture:

- design the hydrator so raw content is optional
- do not make the first implementation depend on raw content being perfect

## Hydrated document shape

The analysis layer should normalize upstream inputs into one internal payload.

Suggested internal shape:

```json
{
  "research_id": 12345,
  "document_hash": "sha256...",
  "source": "JPMorgan",
  "source_date": "2026-03-27",
  "title": "Rates outlook",
  "metadata": {
    "publisher": "JPMorgan",
    "region": "US",
    "asset_focus": "Rates"
  },
  "themes": [
    {
      "theme_id": 1,
      "theme_order": 1,
      "label": "Higher term premium",
      "context": "...",
      "classification": "Forecast",
      "confidence": "High",
      "argument_structure": {},
      "excerpts": ["..."]
    }
  ],
  "raw_content": null
}
```

## Integration assumptions to validate

Another agent should confirm these against the real upstream systems:

- whether `state.db` actually exposes `completed_at` and stable `research_id`
- whether parsed DB access is direct Postgres, Supabase, or an API wrapper
- whether raw content is available and where
- whether theme excerpts carry ordering or span metadata
- whether parser rewrites existing `research_id`s or mostly creates new rows for changed docs

## Compatibility rules

The analysis layer should:

- tolerate missing optional metadata
- tolerate absence of raw content
- require normalized themes for meaningful operation
- avoid making schema assumptions outside this contract until validated

## Recommended validation tasks

Before coding begins, another agent should:

1. inspect a real `state.db` schema
2. inspect real parsed DB tables
3. map real upstream fields to this contract
4. note mismatches in a follow-up doc
5. update this contract with verified field names and examples

Execution details for that validation pass live in:

- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)

## Acceptance criteria

This contract is sufficient when:

- a coding agent can build adapters around it
- upstream inspection has a concrete checklist
- missing or partial upstream data has explicit handling rules

## Related documents

- [2026-03-29-analysis-upstream-validation-results-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-results-spec.md)
- [2026-03-29-analysis-upstream-validation-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-29-analysis-upstream-validation-plan.md)
- [2026-03-27-job-orchestration-and-operations-plan.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-job-orchestration-and-operations-plan.md)
- [2026-03-27-analysis-repo-bootstrap-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-03-27-analysis-repo-bootstrap-spec.md)

## Status

`VALIDATED_WITH_RESULTS_SPEC`
