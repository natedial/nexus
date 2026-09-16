# Release Checklist

Use this checklist to validate quality before deploying a new branch to production.

## Code Quality
- `pytest`
- `ruff check .`
- `ruff format .` (if formatting is enforced in the repo)
- Confirm new config keys in `src/config.py` are used and documented.

## Parser
- Run `scripts/test_full_pipeline.py` on a small, representative PDF set.
- Confirm source artifacts (`document.md`, `blocks.jsonl`, `clean_text.md`) and spans are written.
- Confirm filename identity (`YYYY-MM-DD_GS_...`) is stored on `parsed_research`.
- Confirm a reparse does not wipe `research_themes` or index columns.

## Drive Watcher
- Run `scripts/test_drive.py --days N`.
- Confirm Drive folder ID and service account permissions.
- Verify `RESEARCH_PARSER_POLL_INTERVAL_MINUTES` and `RESEARCH_PARSER_CATCHUP_DAYS` behavior.

## Supabase Storage
- Run `scripts/test_supabase.py`.
- Confirm schema and required fields are satisfied.
- Verify span writes fail closed and `storage_ok` is set only after a successful upsert.

## State DB (SQLite)
- Run `scripts/inspect_state.py --failed`.
- Confirm error messages are recorded on failures.
- Validate state transitions: `pending -> parsing -> storing -> completed/partial/failed`.

## Deployment Readiness
- `docker compose build`
- `docker compose up -d` and verify logs.
- Confirm mounted paths exist: `data/`, `credentials/`, `config/`.

## Operational Readiness
- Verify logs via `docker compose logs -f`.
- Ensure alerting exists for crash loops and zero processed files.
- Define metrics: processed_count per poll, error rate per step.
- Confirm backup policy for Supabase and `data/state.db`.

## Release Gate
- Run in staging with real PDFs.
- No regression in processed counts or error rates.
- Confirm downstream consumers ingest new records.
