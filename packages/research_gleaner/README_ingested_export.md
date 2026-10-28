# Ingested-research export

A small read-only job that dumps recently ingested Nexus research to
`packages/research_gleaner/ingested_recent.json`. The scheduled 6:45 AM
talking-points task reads this file because its sandbox cannot reach this
Mac's Postgres.

- **Source:** `parsed_research`, keyed on `created_at` (parser insert time).
- **Window:** last 48 hours by default (`--hours N` to change).
- **Access:** SELECT only, in a read-only session
  (`default_transaction_read_only=on`). Credentials come from the Nexus `.env`
  files and are never printed or written to the output.
- **Writes:** atomic (temp file, then rename). If the query fails the script
  exits non-zero and the previous file is left untouched.

## Output shape

```json
{
  "generated_at": "2026-10-28T06:30:02-04:00",
  "window_hours": 48,
  "count": 12,
  "documents": [
    {
      "id": 1796,
      "document_id": "<drive file id>",
      "title": "The case for reducing Treasury long-end issuance",
      "raw_title": "2026-10-28_DB__The_case_for_..._DB",
      "publisher": "Deutsche Bank",
      "ingested_at": "2026-10-28T06:18:50-04:00",
      "publication_date": "2026-10-28",
      "url": "https://drive.google.com/file/d/.../view",
      "text": "cleaned excerpt, about 4000 chars…",
      "text_truncated": true,
      "full_text_chars": 39028
    }
  ]
}
```

Consumers should compare `generated_at` with the current time. If it is older
than the expected 6:30 run, the file is stale (see Sleep below).

## Schedule

LaunchAgent `com.ncdial.nexus-ingested-export` runs Mon-Fri at 6:30 local
time. Logs: `~/Library/Logs/nexus-ingested-export/export.{out,err}.log`.
If the Mac is asleep at 6:30, launchd runs the missed job on wake, which can
be after 6:45; check `generated_at`.

## Run by hand

```bash
cd packages/research_gleaner
.venv/bin/python3 scripts/export_ingested_recent.py            # default 48h
.venv/bin/python3 scripts/export_ingested_recent.py --hours 72
launchctl kickstart gui/$(id -u)/com.ncdial.nexus-ingested-export
```

## Install / uninstall

The plist template lives in `launchd/com.ncdial.nexus-ingested-export.plist`.

```bash
cp launchd/com.ncdial.nexus-ingested-export.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ncdial.nexus-ingested-export.plist
```

```bash
launchctl bootout gui/$(id -u)/com.ncdial.nexus-ingested-export
rm ~/Library/LaunchAgents/com.ncdial.nexus-ingested-export.plist
```
