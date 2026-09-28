# Economic Forecast Projections Spec

Last updated: 2026-03-30 America/New_York

## Goal

Define a new forecast-capture layer for `research_analysis_layer` that:

- identifies structured economic forecasts from bank research
- stores forecast candidates locally first
- uploads approved forecasts to a dedicated Supabase table
- links those forecasts to the canonical `economic_events` release row when possible

This spec is intentionally separate from the current document-analysis bootstrap.

## Why a new table is required

The existing `economic_events` table is event-calendar shaped.

It is not a good fit for bank-level forecast rows because:

- one event can have many source forecasts
- one event may have both a market consensus and several house views
- forecast provenance needs to be preserved per report
- some forecasts will be numeric point estimates, some ranges, and some directional only

So the correct model is:

- keep `economic_events` as the canonical release/event row
- add a new `economic_event_forecasts` table for source-specific projections

## Ownership boundary

Parser-owned:

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`

Analysis-owned local staging:

- forecast candidate extraction
- review state
- upload queue state

Supabase app-owned durable forecast destination:

- `economic_event_forecasts`

This layer should not mutate parser-owned tables.

## Data flow

### Phase 1: local forecast candidate extraction

Input:

- `analysis_chunks`
- `analysis_assertions`
- parser metadata mirrored in `analysis_documents`

Selection rule:

- only consider assertions where `assertion_type = 'forecast'`

Output:

- one local forecast candidate row per extracted forecast claim

### Phase 2: normalization and event matching

For each candidate:

- classify the target indicator
- parse any numeric forecast value
- parse forecast unit
- infer release date or reference period where possible
- attempt to resolve a matching `economic_events.id`

Output:

- normalized candidate ready for human review or automatic upload

### Phase 3: controlled upload

Only approved or high-confidence candidates should be uploaded to Supabase.

Upload path:

- read from local forecast candidate store
- write to `economic_event_forecasts`
- update local upload status

This uploader must be a separate command from the main analysis/backfill path.

## Recommended local staging tables

Use local SQLite first, alongside the existing analysis store.

### `forecast_candidates`

Purpose:

- persist extracted forecast candidates before any external write

Recommended fields:

- `id`
- `research_id`
- `file_id`
- `document_hash`
- `source`
- `source_date`
- `document_name`
- `document_link`
- `chunk_order`
- `assertion_order`
- `assertion_text`
- `summary_text`
- `evidence_text`
- `indicator_key`
- `event_name`
- `country`
- `period_text`
- `release_date`
- `forecast_type`
- `forecast_value_numeric`
- `forecast_value_low`
- `forecast_value_high`
- `forecast_value_text`
- `forecast_unit`
- `qualifier_text`
- `extraction_confidence`
- `match_status`
- `matched_economic_event_id`
- `review_status`
- `review_notes`
- `upload_status`
- `uploaded_at`
- `created_run_id`
- `created_at`
- `updated_at`

Suggested `match_status` values:

- `unmatched`
- `matched_exact`
- `matched_fuzzy`
- `ambiguous`
- `no_event_found`

Suggested `review_status` values:

- `pending`
- `approved`
- `rejected`
- `needs_human_review`

Suggested `upload_status` values:

- `not_uploaded`
- `uploaded`
- `failed`

Recommended uniqueness rule:

- unique on `(research_id, chunk_order, assertion_order, indicator_key, forecast_value_text)`

### `forecast_candidate_matches`

Optional helper table if matching becomes non-trivial.

Purpose:

- store alternate candidate event matches for auditability

Recommended fields:

- `id`
- `forecast_candidate_id`
- `economic_event_id`
- `match_score`
- `match_reason`
- `selected`
- `created_at`

This can be deferred until the first matching pass proves it is needed.

## Recommended Supabase table

### `economic_event_forecasts`

Purpose:

- durable destination for bank-level economic forecasts
- one row per source forecast, not one row per event

Recommended logical schema:

```sql
CREATE TABLE public.economic_event_forecasts (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  economic_event_id uuid NULL REFERENCES public.economic_events(id),
  parsed_research_id bigint NULL REFERENCES public.parsed_research(id),

  source text NOT NULL,
  source_date date NULL,
  document_name text NULL,
  document_link text NULL,
  document_hash text NULL,

  indicator_key text NOT NULL,
  event_name text NOT NULL,
  country text NULL,
  period text NULL,
  release_date date NULL,

  forecast_type text NOT NULL,
  forecast_value_numeric numeric NULL,
  forecast_value_low numeric NULL,
  forecast_value_high numeric NULL,
  forecast_value_text text NOT NULL,
  forecast_unit text NULL,

  qualifier_text text NULL,
  extraction_confidence text NULL,
  evidence_text text NOT NULL,

  review_status text NOT NULL DEFAULT 'pending',
  upload_source text NOT NULL DEFAULT 'research_analysis_layer',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT economic_event_forecasts_pkey PRIMARY KEY (id),
  CONSTRAINT economic_event_forecasts_review_status_check
    CHECK (review_status IN ('pending', 'approved', 'rejected', 'uploaded'))
);
```

Recommended indexes:

- index on `(economic_event_id)`
- index on `(indicator_key, release_date)`
- index on `(source, source_date)`
- unique or semi-unique constraint on `(parsed_research_id, indicator_key, forecast_value_text, release_date)`

## Why `economic_event_id` should be nullable

Not every forecast will match a known event row on the first pass.

Examples:

- the report references `March payrolls` without naming the release date
- the event calendar row has not been loaded yet
- the report refers to a broader release family rather than a specific calendar event

So uploads should allow:

- matched rows with `economic_event_id`
- unmatched rows that can be reconciled later

## Extraction contract

The extractor should produce a candidate only when it can identify:

- a forecast claim
- a plausible target indicator
- enough evidence text to support later review

The extractor does not need perfect event matching on day one.

### Required output fields

- `indicator_key`
- `event_name`
- `forecast_type`
- `forecast_value_text`
- `evidence_text`
- report provenance fields

### Strongly preferred fields

- `forecast_value_numeric`
- `forecast_unit`
- `release_date`
- `period_text`

## Initial indicator scope

Keep the first pass narrow and deterministic.

Recommended initial scope:

- `us_nfp`
- `us_cpi_headline_mom`
- `us_cpi_core_mom`
- `us_cpi_headline_yoy`
- `us_cpi_core_yoy`
- `us_core_pce_mom`
- `us_core_pce_yoy`
- `us_retail_sales`
- `us_unemployment_rate`
- `fed_funds_rate`

Do not attempt broad open-world macro extraction in the first version.

## Example normalization

Input claim:

- `Goldman Sachs forecasts +57k jobs in NFP for April 3`

Expected candidate output:

- `source = Goldman Sachs`
- `source_date = 2026-03-30`
- `indicator_key = us_nfp`
- `event_name = Nonfarm Payrolls`
- `country = US`
- `release_date = 2026-04-03`
- `forecast_type = point`
- `forecast_value_numeric = 57000`
- `forecast_value_text = +57k jobs`
- `forecast_unit = jobs`
- `evidence_text = ...`

If a matching `economic_events` row exists for the same release:

- set `economic_event_id`

If not:

- leave `economic_event_id = null`
- keep `match_status = no_event_found`

## Matching rules for `economic_events`

Attempt to match using the following priority order:

1. exact release date + normalized event name + country
2. exact release date + `indicator_key`
3. inferred period + close event date + normalized event name

Treat these as non-match conditions:

- multiple candidate events with similar scores
- release date missing and period ambiguous
- country mismatch

When matching is ambiguous:

- keep the forecast candidate
- do not auto-upload without review

## Confidence and review policy

Recommended auto-approval posture for the first version:

- only auto-approve point estimates with numeric values
- only auto-approve candidates with a recognized `indicator_key`
- only auto-approve candidates with one unambiguous event match or a clear release date
- send everything else to `needs_human_review`

Examples that should require review:

- directional forecasts without a number
- multiple numbers in the same forecast sentence
- unclear whether the value refers to month-over-month or year-over-year
- release family named without a date

## Upload boundary

Add a dedicated uploader command later, for example:

- `extract-forecasts`
- `review-forecast-candidates`
- `upload-forecasts`

Do not make `run` or `backfill` write to Supabase forecasts directly.

Reason:

- analysis backfills should remain locally reversible
- forecast uploads affect a shared app-facing table
- review and approval should remain explicit

## Recommended implementation sequence

### Step 1

Add local SQLite tables for `forecast_candidates`.

### Step 2

Add a deterministic forecast extractor that reads `forecast` assertions plus chunks and evidence.

### Step 3

Add indicator-specific normalization rules for the first small set of indicators.

### Step 4

Add `economic_events` matching logic with explicit `match_status`.

### Step 5

Add a review CLI that lists pending candidates.

### Step 6

Add a separate Supabase uploader for approved candidates only.

## Acceptance criteria

This spec is satisfied when:

- the analysis layer can extract forecast candidates locally from existing forecast assertions
- candidates preserve full provenance back to `parsed_research.id`
- ambiguous candidates are held locally and not uploaded
- approved candidates can be inserted into `economic_event_forecasts`
- uploaded rows can be linked back to `economic_events.id` when available
- the live write boundary to Supabase remains a separate explicit step

## Open questions

- whether there is an existing indicator metadata table elsewhere that should also be linked
- whether `economic_events.event_name` is normalized enough for deterministic matching
- whether release dates should be matched in New York time or pure calendar date only
- whether a second table is needed later for realized-versus-forecast comparisons

## Recommendation

Proceed with:

- local `forecast_candidates` support in this repo first
- a new Supabase `economic_event_forecasts` table second
- no direct automatic upload from the main analysis pipeline

That gives the team a safe audit trail and preserves the current low-risk rollout posture.
