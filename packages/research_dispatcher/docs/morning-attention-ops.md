# Morning attention ops wiring (credentials / host)

Cadence: **weekdays 06:25 America/New_York**, after the 06:10 digest. Does **not** change 5:55 / 6:10 tablet pushes.

## Env vars (package `.env` or process env)

| Variable | Purpose |
| --- | --- |
| `RESEARCH_DISPATCHER_NOTION_TOKEN` | Notion integration secret (read LIBRARY DB) |
| `RESEARCH_DISPATCHER_NOTION_LIBRARY_DATABASE_ID` | Default `2839852e-ebb4-806c-9127-c229dcc2ddb9` (from https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9) |
| `RESEARCH_DISPATCHER_REMARKABLE_DROP_DIR` | Local drop dir for own-surface `.md` notebook (Remarkdown ingest) |
| `RESEARCH_DISPATCHER_REMARKABLE_PUSH_URL` | Optional HTTP push endpoint (Remarkdown-compatible) |
| `RESEARCH_DISPATCHER_REMARKABLE_PUSH_TOKEN` | Optional bearer for push URL |
| `RESEARCH_DISPATCHER_CHAT_PING_TO` | One-line chat ping recipients (defaults to `RESEARCH_DISPATCHER_EMAIL_TO`) |
| `RESEARCH_DISPATCHER_SMTP_*` / `EMAIL_FROM` | Same SMTP pattern as other briefs |
| `RESEARCH_DISPATCHER_MORNING_WATERMARK` | Override watermark path (default `state/morning_attention_last_run.json`) |
| `RESEARCH_DISPATCHER_MORNING_NOTES_JSONL` | Claim-note input for the schedule script |
| `RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON` | Optional argument_map batch instead of JSONL |

## Notion setup (Nate)

1. Create/share a Notion integration with read access to the LIBRARY database.
2. Put the secret in `RESEARCH_DISPATCHER_NOTION_TOKEN`.
3. Confirm the DB has a **Resource Type** select property including `Research Note`.
4. Share the LIBRARY database with the integration (same DB the 6:10 digest uses).

## Host schedule

```bash
# cron — set CRON_TZ so 6:25 is Eastern
CRON_TZ=America/New_York
25 6 * * 1-5 /path/to/nexus/packages/research_dispatcher/schedule_morning_attention.sh >> /path/to/logs/morning_attention.cron.log 2>&1
```

Or load `launchd/com.researchdispatcher.morning-attention.plist` after editing paths.

## Manual dry run (no secrets required for fakes)

```bash
cd packages/research_dispatcher
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json \
  --dry-run --fake-delivery
```
