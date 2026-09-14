# Scrivener release calendar fix handoff

## Purpose

Capture the Scrivener-side calendar issues blocking forecast matching in `research_analyst`, summarize the live evidence collected on April 3, 2026, and hand off a concrete repair plan for the Scrivener team.

## Why this matters

`research_analyst` now reads parsed research from Proton Parser, matches forecast rows against Scrivener `release_dates`, and writes matched forecast rows back into Proton.

That split is working technically. The current blocker is data quality in Scrivener's release calendar.

Observed result after the two-project cutover:

- `1` forecast from `research_id=5194` matched and uploaded successfully
- `10` forecasts remained unmatched
- the matched row was `ADP`
- the unmatched rows were mainly payrolls, retail sales, and ISM-related forecasts

## Current symptom

The immediate problem is not in `research_analyst` matching logic. It is upstream coverage in Scrivener `release_dates`.

Live findings:

- Scrivener returned no `release_dates` rows for `2026-04-03`
- Scrivener did return `ADP National Employment Report` on `2026-04-01`
- Scrivener contains the `Employment Situation` release record, but its future dates are incomplete
- Scrivener does not appear to contain a clean canonical release family for `ISM Manufacturing`
- Scrivener does not appear to contain a clean canonical release family for headline `Retail Sales`

Practical effect:

- `ADP` can match
- `Employment Situation` should match, but its April 3 release date is missing
- `Retail Sales` and `ISM Manufacturing` are not reliable matches under the current FRED-release-only model

## Evidence collected

### 1. `2026-04-03` is empty in Scrivener `release_dates`

Direct live query result:

- `release_dates` rows on `2026-04-03`: `0`

This is the date needed for the March employment report forecasts extracted from the Morgan Stanley note.

### 2. `Employment Situation` exists, but its schedule is sparse

Live release lookup found:

- `releases.id = 18`
- `fred_release_id = 50`
- `name = Employment Situation`

Stored future release dates for that release currently include:

- `2026-01-09`
- `2026-03-06`
- `2026-06-05`

The expected `2026-04-03` row is missing.

That strongly suggests a bad sync result rather than a naming problem.

### 3. `ADP` is present and does match

Live release lookup found:

- `releases.id = 96`
- `fred_release_id = 194`
- `name = ADP National Employment Report`

Stored future release dates currently include:

- `2026-01-07`
- `2026-03-04`
- `2026-04-01`
- `2026-06-03`
- `2026-07-01`

This lines up with the one forecast that successfully matched and uploaded from `research_id=5194`.

### 4. Upcoming calendar volume exceeds 1000 rows

For the upcoming `2026-04-03` to `2026-07-02` window, the live API response indicated:

- `Content-Range: 0-999/1005`

Important clarification:

- this `Content-Range` format is from PostgREST or Supabase, not from FRED itself
- it does not prove what FRED returned on the wire
- it does confirm that at least one downstream API path exposed a result set larger than 1000 rows in the relevant window

That does not prove the FRED sync bug by itself, but it reinforces the pagination risk. A sync path that only consumes one FRED page is not safe when the upstream endpoint supports paginated result sets that can exceed the default limit.

### 5. Scrivener scheduler depends on populated `release_dates`

The Scrivener README explicitly says release-based scheduling depends on these rows being populated:

- [README.md](/Users/ncdial/devwork/sophia_engine/services/scrivener/README.md#L90)

This means stale or partial `release_dates` is not just an analyst problem. It can degrade Scrivener's own scheduled ingestion behavior.

## Likely root cause

The strongest current hypothesis is that Scrivener's FRED calendar sync is not safely handling complete result sets, and then treats a partial snapshot as authoritative.

Relevant code:

- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py#L232) fetches all releases in one call
- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py#L251) fetches all release dates in one call
- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py#L336) syncs release dates into the database
- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py#L396) deletes future rows not present in the fetched set

What the code does now:

1. Fetch one response from FRED `releases`
2. Fetch one response from FRED `releases/dates`
3. Treat that returned set as the full desired state
4. Delete future `release_dates` rows that are not in that desired set

Why this is dangerous:

- if the upstream fetch is partial for any reason, future dates can be missed during insert
- if a release appears in the truncated result but its individual date set is incomplete, legitimate future dates for that release can also be removed
- the current `Employment Situation` gaps are consistent with that failure mode
- the current code has no visible completeness guard before deletion

Important nuance:

- the current evidence does not prove whether the missing `2026-04-03 Employment Situation` row was never inserted or was inserted previously and later deleted
- the code supports both failure modes
- the fix is the same either way: paginate safely and never perform destructive cleanup from an incomplete snapshot

## Important nuance

There are probably two separate problems:

### Problem A: sync correctness bug

`Employment Situation` should exist in Scrivener and should have matched this workflow. Its missing April 3 date points to a sync bug.

### Problem B: source coverage gap

Even after fixing the sync, `release_dates` alone is unlikely to cover every forecast family the analyst pipeline needs.

Examples from live inspection:

- no clean `ISM Manufacturing` release family
- no clean headline `Retail Sales` release family

That means a pure "fix pagination and we're done" approach will still leave gaps.

## Proposed fix plan

### Phase 0: contain the destructive path

Before adding pagination, stop unsafe deletions from causing further calendar loss.

Important implementation detail from Scrivener:

- release calendar reads can auto-trigger a sync when the local table is empty or stale
- that behavior currently lives in `src/query/releases.py`
- an unsafe sync is therefore not limited to explicit maintenance runs; it can also happen on a normal read path

Immediate recommendation:

1. Make `sync_release_dates()` non-destructive unless the upstream fetch is known complete
2. If needed, temporarily disable deletion entirely until completeness checks are in place
3. Consider temporarily disabling read-path auto-sync if that path could still invoke unsafe deletion before the patch lands

This is the fastest way to prevent additional accidental shrinking of future `release_dates`.

### Phase 1: make the existing FRED sync safe and complete

Target file:

- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py)

Recommended changes:

1. Prioritize pagination of `fetch_release_dates()`
2. Only run deletion logic when the fetch is known complete
3. Emit sync metrics that make incompleteness visible
4. Add explicit tests for deletion safety and pagination completeness
5. Paginate `fetch_releases()` as a secondary hygiene fix

Implementation notes:

- use FRED `limit` and `offset` query parameters and consume all pages before constructing the desired-state set
- determine completeness from the FRED response body metadata such as `count`, `limit`, and `offset`, not from HTTP range headers
- if pagination fails or completeness cannot be established, insert/update only and skip deletion
- log at least: `fetched_count`, `inserted`, `skipped`, `removed`, `complete=true|false`
- keep the sync result structured enough that callers can tell whether the run was complete or degraded
- `releases/dates` is the live blocker because it returns one row per dated event and is much more likely to exceed the default page size than `releases`

Test coverage that should be added as part of this phase:

- paginated `fetch_release_dates()` returns the full result set across multiple pages
- `sync_release_dates()` deletes stale rows only when the fetched snapshot is complete
- `sync_release_dates()` performs insert/update only and skips deletion when the snapshot is incomplete
- anchor validation fails loudly when critical upcoming releases disappear unexpectedly
- paginated `fetch_releases()` returns the full result set across multiple pages

This is the minimum repair needed to stop silently deleting valid future dates.

### Phase 2: add release-calendar integrity checks

Add a post-sync validation step that asserts anchor releases exist on expected upcoming dates.

Suggested anchors:

- `Employment Situation`
- `ADP National Employment Report`
- any other release families Scrivener operational flows depend on

Suggested behavior:

- fail the sync job loudly if anchor coverage disappears unexpectedly
- alert rather than silently accepting an empty or sparse future calendar

This would have caught the missing `2026-04-03 Employment Situation` row immediately.

### Phase 3: recover and validate end-to-end behavior

After the sync patch lands:

1. Run a manual Scrivener release sync with a `days_ahead` window large enough to cover all affected upcoming dates, not just the default horizon
2. Backfill `release_dates` from a now-safe upstream snapshot
3. Verify `Employment Situation` includes `2026-04-03`
4. Verify `release_dates` on `2026-04-03` are no longer empty
5. Rerun analyst matching for `research_id=5194`
6. Record exactly which forecast families still do not match after the calendar is repaired

This phase is important because it separates:

- rows that failed because the Scrivener calendar was corrupted
- rows that still fail because Scrivener lacks canonical analyst-facing normalization

### Phase 4: make Scrivener the analyst-facing system of record

This is the strategic fix.

The analyst matching job should not depend forever on raw FRED release names alone. Scrivener should own canonical macro-event normalization and expose a stable analyst-facing event model.

Important repo context:

- Scrivener already contains a partial normalization layer in `src/scheduler/calendar.py`, where raw release names are mapped by regex into operational release families
- that scheduler regex layer is not shared infrastructure today; it is consumed only by the scheduler path
- Scrivener also has an `economic_events` table, but that table stores extracted document events and forecast or result provenance rather than source-of-truth scheduled releases

That means the long-term design should not reuse `economic_events` as the canonical release schedule. The right direction is a dedicated canonical calendar layer that is clearly downstream of raw source releases.

Opinionated recommendation:

- Scrivener should own canonical macro-event normalization
- the canonical model should be shared across scheduler, API, and analyst use cases
- use the existing scheduler regexes as a starting vocabulary only, not as the final shared implementation
- avoid keeping critical normalization logic only as regexes embedded in scheduler code
- prefer a first-class stored model over duplicated name-matching logic across projects

Suggested shape:

- table name: `calendar_events` or similar
- one row per canonical event instance
- normalized keys such as:
  - `us_nfp`
  - `us_adp_employment_change`
  - `us_retail_sales_headline_mom`
  - `us_retail_sales_ex_auto_mom`
  - `us_retail_sales_control_group_mom`
  - `us_ism_manufacturing`
- include:
  - canonical key
  - event name
  - country
  - release date
  - period
  - source system
  - source event id

Population strategy:

- keep FRED as one source
- add other source feeds when FRED does not provide clean coverage
- do not assume every important macro release has a usable FRED release family

This gives `research_analyst` a stable matching target instead of forcing it to reverse-engineer source-specific release taxonomies.

Important sequencing note:

- do not finalize this schema decision until after Phase 3
- after the safe resync, reevaluate whether `Retail Sales` and `ISM Manufacturing` are true source-coverage gaps or mostly canonical-name-mapping gaps
- FRED may already expose more usable release families than the current handoff evidence suggests; the missing piece may be normalization rather than source absence

## Recommended sequencing

1. Contain the destructive sync path first
2. Patch pagination and completeness handling in Scrivener sync
3. Add tests for pagination, deletion safety, and anchor validation
4. Backfill and resync `release_dates`
5. Verify `Employment Situation` includes `2026-04-03`
6. Verify `release_dates` for `2026-04-03` are no longer empty
7. Rerun analyst matching for `research_id=5194`
8. Confirm which payroll-related rows now match
9. Identify the residual unmatched families after the calendar repair
10. Define a dedicated canonical calendar layer for analyst-facing matching, informed by the residual unmatched families after recovery

## Acceptance criteria

Minimum acceptable outcome:

- `Employment Situation` has a `2026-04-03` release date in Scrivener
- the future release calendar is no longer silently shrinking from partial syncs
- sync logs clearly indicate whether the source snapshot was complete
- Scrivener no longer performs destructive release-date cleanup on an incomplete fetch
- automated tests cover the safe/incomplete sync path

Better outcome:

- analyst rerun matches both `ADP` and `Employment Situation`-based rows

Longer-term correct outcome:

- Scrivener owns the canonical analyst-facing macro-event model
- analyst matching targets that canonical Scrivener model instead of raw FRED `release_dates`

## Validation checklist

After the Scrivener patch:

1. Run Scrivener release sync manually
2. Query `Employment Situation` future dates and confirm `2026-04-03` exists
3. Query all `release_dates` on `2026-04-03` and confirm the day is no longer empty
4. Rerun:
   - `research_analysis_layer.main extract-forecasts --research-id 5194 --rebuild`
5. Rerun:
   - `research_analysis_layer.main upload-forecasts --limit 50`
6. Verify Morgan Stanley payroll forecasts no longer return `no_event_found`
7. Record which non-payroll forecast families still return `no_event_found`
8. Use that residual list to drive canonical normalization scope in Scrivener

## Open questions

These should be decided during implementation:

- does FRED provide enough release coverage for the specific retail-sales and ISM families the analyst system needs
- what schema should Scrivener use for a dedicated canonical calendar layer, and how should that layer relate to raw source releases and downstream analyst matching
- should `release_dates` continue to support deletion-based reconciliation, or should future rows be soft-reconciled with explicit source completeness checks first

## Recommended owner handoff

This work belongs in the Scrivener repo, not `research_analyst`.

Relevant implementation area:

- [fred.py](/Users/ncdial/devwork/sophia_engine/services/scrivener/src/fetchers/fred.py)

Relevant downstream consumer:

- [forecast_matcher.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/forecast_matcher.py)

If only one fix can be made immediately, make it this:

- stop deleting future `release_dates` rows unless the FRED fetch is confirmed complete
