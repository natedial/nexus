# Forecast extraction and matching handoff

## Purpose

Capture the current implementation state of the economic-forecast pipeline, the specific fixes completed during the March 31 work session, and the remaining blockers before forecast rows can attach to canonical `economic_events` rows and upload cleanly.

## Current status

The forecast workflow is now in a materially better state than the March 30 spec baseline:

- standalone forecast parsing can be run with `extract-forecasts --dry-run`
- raw parsed report text can be mined directly for calendar-style macro forecasts
- extracted rows now cover table-style notes that the normalized theme layer was abstracting away
- the `economic_events` matcher no longer fails on a broken schema assumption
- unmatched forecasts now degrade to `no_event_found` instead of `event_lookup_error`

The core remaining issue is upstream data coverage in `economic_events`, not local extraction logic.

## Completed work

### 1. Standalone no-write forecast testing

Implemented a real no-write preview path for forecast extraction:

- `extract-forecasts --dry-run`
- supports `--rebuild`
- does not delete local candidates
- does not write local candidates
- does not upload anything

This makes it safe to test the forecast workflow repeatedly against the current local corpus.

## 2. Raw-text forecast mining

Added a dedicated raw-text extractor in [src/research_analysis_layer/services/raw_forecast_extractor.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/raw_forecast_extractor.py).

This extractor reads `parsed_research.parsed_data.full_text` directly and is now wired into `extract-forecasts` in [src/research_analysis_layer/main.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/main.py).

Supported forecast families now include:

- employment prose blocks
- employment schedule/table rows
- ADP
- retail sales headline
- retail sales ex-auto
- retail sales control group
- ISM manufacturing
- unemployment rate
- average hourly earnings
- labor force participation
- average weekly hours

### 3. Morgan Stanley validation case

Target document:

- `parsed_research.id = 5194`
- `2026-03-29_MS__When_do_higher_oil_prices_shift_risk_from_inflation_to_growth__What_to_watch_UNITED_20260327_0500.pdf`

This note was used as the main validation case because:

- the explicit forecast rows existed in `full_text`
- most of them did not survive into normalized themes
- the old forecast path therefore missed them

Current dry-run result for `research_id 5194`:

- `candidate_count = 11`
- `stored_count = 0`
- `would_store_count = 11`

Recovered rows:

- `us_nfp = +60k`
- `us_private_payrolls = +70k`
- `us_unemployment_rate = 4.4%`
- `us_average_hourly_earnings_mom = +0.3%`
- `us_average_weekly_hours = 34.3`
- `us_labor_force_participation_rate = 62.0%`
- `us_adp_employment_change = +40k`
- `us_retail_sales_headline_mom = +0.6%`
- `us_retail_sales_ex_auto_mom = +0.3%`
- `us_retail_sales_control_group_mom = +0.2%`
- `us_ism_manufacturing = 53.0`

### 4. Metadata reconciliation between prose and table rows

The raw extractor now merges metadata between prose-derived and table-derived candidates for the same series.

This fixed two important issues in the Morgan Stanley note:

- employment prose rows now inherit `March 2026` instead of incorrectly drifting to `February 2026`
- employment prose rows now inherit `release_date = 2026-04-03` from the schedule table

### 5. `economic_events` matcher repair

The previous matcher bug was not primarily semantic. It was querying the wrong schema field.

Before the fix:

- `search_economic_events(...)` queried `release_date`
- the live `economic_events` table uses `event_date`
- every lookup returned HTTP 400
- candidates fell into `event_lookup_error`

Completed fixes:

- updated the client in [src/research_analysis_layer/db/parsed_db_client.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/db/parsed_db_client.py) to query `event_date`
- expanded selected fields to include `event_name`, `event_date`, `country`, `period`, and `time_ny`
- updated the matcher in [src/research_analysis_layer/services/forecast_matcher.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/forecast_matcher.py) to:
  - fetch same-day event rows
  - resolve matches locally using indicator-key alias sets
  - prefer stronger event-name matches and period alignment when available

Alias examples now supported:

- `us_nfp` -> `Change in Nonfarm Payrolls`, `Nonfarm Payrolls`
- `us_private_payrolls` -> `Change in Private Payrolls`, `Private Payrolls`
- `us_adp_employment_change` -> `ADP Employment Change`, `ADP Employment Weekly`
- `us_retail_sales_headline_mom` -> `Retail Sales Advance m/m`, `Retail Sales`

### 6. Behavior after matcher repair

After the matcher fix, the Morgan Stanley dry-run no longer produces `event_lookup_error`.

It now correctly returns:

- `match_status = no_event_found`

for all 11 extracted rows.

This is the right result given the current upstream table contents.

## What remains

### 1. Upstream `economic_events` coverage is missing for the target dates

The live `economic_events` table currently tops out at:

- latest `event_date = 2025-12-24`

There are no US rows for:

- `2026-04-01`
- `2026-04-03`

So the local matcher is now working, but there are no canonical rows to attach these forecasts to.

Practical implication:

- extracted forecasts can be staged locally
- they can be marked `approved`
- they cannot yet resolve to `economic_events.id`
- upload behavior should remain cautious until upstream event coverage is current

### 2. Confirm canonical event taxonomy once upstream coverage exists

The current alias map is a practical starting point, not a fully audited ontology.

Once `economic_events` is populated through the relevant release window, validate that canonical naming for these families is stable:

- payrolls
- unemployment
- AHE
- labor force participation
- retail sales
- ISM manufacturing
- ADP

Acceptance check:

- rerun `extract-forecasts --research-id 5194 --rebuild --dry-run`
- confirm at least some rows move from `no_event_found` to `matched_exact`

### 3. Decide whether upload should require a canonical event match

Current behavior allows a candidate to be `approved` with `match_status = no_event_found` as long as:

- it has a numeric point forecast
- it has a release date

That is reasonable for local review, but the team should decide whether durable upload into `economic_event_forecasts` should require:

- a non-null `economic_event_id`
- or whether unmatched source forecasts are acceptable in the destination table

### 4. Broader corpus validation

The raw-text path is now validated against the Morgan Stanley note, but it should be checked against a broader golden set.

Recommended next set:

- 20 to 30 notes with explicit watch-week forecast tables
- multiple banks
- a mix of employment, inflation, activity, and retail releases

Targets to measure:

- candidate recall
- numeric accuracy
- release-date accuracy
- false positives
- duplicate suppression quality

## Recommended next steps

1. Refresh or backfill the upstream `economic_events` table so it includes the April 2026 release window and other current dates.
2. Rerun the Morgan Stanley dry run and verify which rows become `matched_exact`.
3. If canonical names differ, extend the alias map rather than changing extraction labels ad hoc.
4. Decide whether unmatched but approved forecasts should upload or remain local until canonical event coverage exists.
5. Build a small golden-set regression pack for recurring forecast-table notes.

## Verification completed

Local test suite:

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- `uv run pytest`

Live scoped validation:

- `PYTHONPATH=src python3 -m research_analysis_layer.main reprocess --research-id 5194`
- `PYTHONPATH=src python3 -m research_analysis_layer.main extract-forecasts --research-id 5194 --rebuild --dry-run`

Observed live outcome after the final matcher fix:

- extraction succeeds
- 11 forecast candidates are recovered
- candidates are `approved`
- candidates are `no_event_found`
- failure mode is now missing upstream canonical events, not local parsing or query errors
