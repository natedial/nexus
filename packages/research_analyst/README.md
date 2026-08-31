# Research Analysis Layer

Bootstrap implementation of the analysis layer planned in [`plans/`](./plans).

This service sits between `research_parser` and `research_dispatcher`.

## Analysis versions

- `argmap-v1` (2026-08-30) — Adds per-document argument_map (author claims with
  rationale + evidence + support_strength). Additive to DocumentAnalysis; cross-document
  consensus and evidence resolution are later slices. Downstream consumers may filter
  analysis_version >= argmap-v1 to require the argument map.
- `bootstrap-v1` — Initial analysis payload. Still the stored version on rows produced
  before this bump; the refit-era prompts shipped without a version change.

Current bootstrap scope:

- read parser success rows from SQLite `state.db`
- hydrate parsed document content from Supabase
- run a deterministic document analysis pass
- persist run state, graph provenance, and intermediate analysis records in a local SQLite analysis store
- stage forecast candidates locally, review them, and upload approved rows separately
- generate local review payloads for analyzed documents

The current upstream contract is documented in:

- [`plans/2026-03-29-analysis-upstream-validation-results-spec.md`](./plans/2026-03-29-analysis-upstream-validation-results-spec.md)

## Quick start

```bash
python -m research_analysis_layer.main doctor
python -m research_analysis_layer.main run --limit 5
python -m research_analysis_layer.main extract-forecasts --limit 25
python -m research_analysis_layer.main sync-forecasts --upload-limit 250
python -m research_analysis_layer.main review-forecast-candidates --review-status pending
python -m research_analysis_layer.main review-document --research-id 1234
```

## Docker hourly runner

The repo now includes a small Docker image and `Makefile` targets for a long-running hourly worker.

Build the image:

```bash
make build
```

Run the hourly worker:

```bash
make run-hourly
```

Useful targets:

- `make doctor`
- `make run-once`
- `make logs`
- `make stop`
- `make shell`

The hourly container:

- runs `doctor` on startup
- wakes up every `POLL_INTERVAL_SECONDS` seconds, default `3600`
- runs `python -m research_analysis_layer.main run --limit ...`
- keeps draining additional batches within the same tick until the queue is exhausted or `MAX_BATCHES_PER_TICK` is reached
- runs `python -m research_analysis_layer.main sync-forecasts --upload-limit ...` after each tick to auto-upload only approved matched forecasts

Expected env configuration:

- `PARSED_DB_URL` and `PARSED_DB_KEY` for Proton Parser
- `CALENDAR_DB_URL` and `CALENDAR_DB_KEY` for the calendar source
- optional `CALENDAR_MATCH_SOURCE` (`economic_events` for legacy single-project mode, `release_dates` for Scrivener-backed matching)
- optional `CALENDAR_SOURCE_NAME` (defaults to `scrivener` when using `release_dates`)
- optional `STATE_DB_PATH`
- optional `ANALYSIS_DB_URL`
- optional `RUN_BATCH_LIMIT`
- optional `MAX_BATCHES_PER_TICK`
- optional `FORECAST_UPLOAD_LIMIT`
- optional `POLL_INTERVAL_SECONDS`

The default container mounts `./data` to `/data` and uses:

- host parser state DB: `../research_parser/data/state.db`
- host analysis directory: `./data`
- host shared ops package: `../research_pipeline_ops`
- `STATE_DB_PATH=/parser-data/state.db`
- `ANALYSIS_DB_URL=sqlite:////data/analysis.db`

Optional environment variables:

- `STATE_DB_PATH`
- `PARSED_DB_URL`
- `PARSED_DB_KEY`
- `CALENDAR_DB_URL`
- `CALENDAR_DB_KEY`
- `CALENDAR_MATCH_SOURCE`
- `CALENDAR_SOURCE_NAME`
- `ANALYSIS_DB_URL`
- `BATCH_SIZE`
- `ANALYSIS_VERSION`
- `BACKFILL_REQUIRE_WARNING_FREE`

## Backfill safety

`backfill` runs in preview mode by default and only writes with `--apply`.

By default, warning-bearing documents are held out of live backfill writes and
show up in preview as `review_required_count`. This keeps broader backfills
limited to high-confidence documents unless you explicitly opt in with
`--allow-warnings`.

## Forecast extraction

`extract-forecasts` reads existing local `forecast` assertions and writes
reviewable forecast candidates into the local SQLite analysis store.

Use `--rebuild` to clear and regenerate local forecast candidates after
changing extraction heuristics.

Use `--dry-run` to preview extraction and event matching without deleting or
writing any local candidates. `--rebuild --dry-run` rescans the full analyzed
corpus with zero side effects.

The forecast workflow is intentionally explicit:

- `extract-forecasts` extracts and event-matches local candidates
- `review-forecast-candidates` shows staged candidates
- `set-forecast-review --candidate-ids ... --review-status approved` updates review state
- `upload-forecasts` writes only approved candidates with a matched `economic_event_id` to Supabase

If an approved candidate is still unmatched, upload is refused, the attempt is
logged, and the local candidate is marked with `upload_status = failed`.

## Review harness

`review-document --research-id ...` emits a JSON review payload with:

- document metadata and last quality report
- chunk boundaries
- assertions
- document-linked world nodes and edges

Each review command also stores a local snapshot in `analysis_reviews`.

## Tests

```bash
uv run pytest
```

For unittest compatibility (legacy):
```bash
uv run python -m unittest discover -s tests
```

By default, the bootstrap expects the adjacent parser repo layout validated on 2026-03-29:

- parser state DB at `../research_parser/data/state.db`
- parsed DB credentials from parser-style Supabase env vars
- local analysis store at `sqlite:///data/analysis.db`
