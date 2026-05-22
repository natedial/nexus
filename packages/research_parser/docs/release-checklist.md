# Release Checklist

Use this checklist to validate quality before deploying a new branch to production.

## Code Quality
- `pytest`
- `ruff check .`
- `ruff format .` (if formatting is enforced in the repo)
- Confirm new config keys in `src/config.py` are used and documented.

## Parser + Extraction
- Run `scripts/test_full_pipeline.py` on a small, representative PDF set.
- Compare outputs to baseline: metadata fields, number of themes/trades, key excerpts.
  - Use `scripts/compare_baseline.py --manifest data/baselines/manifest.json --mode compare`
  - Manifest example:
```json
{
  "documents": [
    { "id": "drive_file_id", "name": "Example.pdf" },
    { "path": "data/golden/Example2.pdf", "name": "Example2.pdf" }
  ]
}
```
- Verify safeguard behavior: boilerplate stripping does not return empty/trivial text.
- Check per-step success flags (`metadata_ok`, `themes_ok`, `trades_ok`) in state DB.

## Drive Watcher
- Run `scripts/test_drive.py --days N`.
- Confirm Drive folder ID and service account permissions.
- Verify `POLL_INTERVAL_MINUTES` and `CATCHUP_DAYS` behavior.

## Supabase Storage
- Run `scripts/test_supabase.py`.
- Confirm schema and required fields are satisfied.
- Verify partial results are inserted and `storage_ok` is set.

## State DB (SQLite)
- Run `scripts/inspect_state.py --failed`.
- Confirm error messages are recorded on failures.
- Validate state transitions: `pending -> parsing -> extracting -> completed/partial/failed`.

## Deployment Readiness
- `docker compose build`
- `docker compose up -d` and verify logs.
- Confirm mounted paths exist: `data/`, `credentials/`, `config/`.
- Ensure the correct `config/models.yaml` is on the host.

## Operational Readiness
- Verify logs via `docker compose logs -f`.
- Ensure alerting exists for crash loops and zero processed files.
- Define metrics: processed_count per poll, error rate per step.
- Confirm backup policy for Supabase and `data/state.db`.

## Release Gate
- Run in staging for 24-48 hours with real PDFs.
- No regression in processed counts or error rates.
- Confirm downstream consumers ingest new records.
