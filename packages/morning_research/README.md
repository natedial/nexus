# morning-research

Daily morning-research automation: a deterministic Python shell around a
Codex judgment core. Every morning it:

1. Pulls newly available research PDFs from a watched Google Drive folder
   (`PDFs_as_Docs`).
2. Prefilters obvious non-research documents (too small, disclosure/legal
   boilerplate filenames) and de-duplicates against previously processed
   documents (by Drive `file_id` and by content hash, to catch renames/copies).
3. Fetches the five most recent prior "Markets Research Note" pages from
   Notion's `LIBRARY` database for historical comparison.
4. Hands the candidate PDFs + prior notes to the Codex CLI (`codex exec`),
   which does the actual reading, analysis, and synthesis per
   [`AGENTS.md`](AGENTS.md), and writes `draft.md` + `receipt.json`.
5. Validates (`qc.py`) the draft and receipt.
6. Publishes the draft as a new page in the Notion `LIBRARY` database.
7. Optionally persists run/document/extraction records to Supabase.
8. Updates a small JSON state file so the next run only looks at genuinely
   new material.

There is no PDF→markdown parsing step in this package — Codex reads the PDFs
directly. (Contrast with `research_parser` / `research_dispatcher`, which
this package does not modify or depend on.)

## Setup

```bash
cd morning_research
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[supabase,dev]"   # drop `supabase` extra if you don't use it
cp .env.example .env
# edit .env with real credentials
```

You'll also need the [Codex CLI](https://github.com/openai/codex) installed
and authenticated (`codex_bin` in `.env`, default `codex`), since
`codex_runner.py` shells out to `codex exec`.

### Environment variables

See [`.env.example`](.env.example) for the full list. Key ones:

| Variable | Purpose |
| --- | --- |
| `GOOGLE_CREDENTIALS_PATH` | Service account JSON with read access to the Drive folder |
| `GOOGLE_DRIVE_FOLDER_ID` | The `PDFs_as_Docs` folder id |
| `NOTION_TOKEN` / `NOTION_DATABASE_ID` | Notion integration token and `LIBRARY` database id |
| `SUPABASE_URL` / `SUPABASE_KEY` | Optional — Supabase persistence is skipped (with a log message) if either is unset |
| `MORNING_RESEARCH_STATE_PATH` | Where the run-state JSON lives (see Migration notes below) |
| `MORNING_RESEARCH_WORK_DIR` | Scratch directory for per-run artifacts (manifest, PDFs, prior notes, draft, receipt) |
| `CODEX_BIN` / `CODEX_TIMEOUT_SECONDS` / `CODEX_MODEL` | Codex CLI invocation settings |
| `MIN_PDF_BYTES` | Prefilter threshold for suspiciously small PDFs |
| `DRY_RUN` | `true` to exercise Drive pull, prior-note fetch, and QC without Codex/Notion publish; does **not** advance the durable state ledger |

## Running

```bash
python -m morning_research
# or, after `pip install -e .`:
morning-research
```

Each run creates `work/<run_id>/` containing:

- `state_snapshot.json` — read-only snapshot of state at run start
- `manifest.json` — candidate documents, prefilter exclusions, skipped duplicates
- `docs/{file_id}.pdf` — downloaded PDFs
- `prior_notes/{i}_{slug}.md` — prior Notion research notes
- `extractions/{file_id}.json` — Codex's per-document extractions
- `draft.md` / `receipt.json` — Codex's final output, validated by `qc.py`

### Dry run

Set `DRY_RUN=true` in `.env` (or export it) to test Drive pull, prior-note
fetch, prefilter, and QC without invoking Codex or Notion publish. A stub
`draft.md`/`receipt.json` is written for QC. Dry runs intentionally leave
`processed_documents` / `last_successful_run` unchanged so real documents are
not marked processed without analysis.

### No-op runs

If Drive listing succeeds but no candidates survive prefiltering/dedup, the
run is a no-op: `last_successful_run` is still advanced (so the next run's
window doesn't keep re-scanning an empty range indefinitely), but
`processed_documents` and `last_created_notion_page_id` are left untouched,
since nothing was actually analyzed or published.

### Failure handling

Any failure before the final state update (Drive errors, Codex non-zero
exit/timeout, QC failure, Notion publish failure) leaves the state file
completely untouched, so the same window — and the same candidate documents —
will be reconsidered on the next run.

## Scheduling

See [`schedule/`](schedule/):

- `run_daily.sh` — wrapper that activates the venv and runs `python -m morning_research`, logging to `work/logs/`
- `com.ncdial.morning-research.plist.example` — launchd job example; copy to `~/Library/LaunchAgents/`, edit the schedule time, then:

```bash
cp schedule/com.ncdial.morning-research.plist.example \
   ~/Library/LaunchAgents/com.ncdial.morning-research.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ncdial.morning-research.plist
```

## Migration notes from `local_codex`

This package supersedes the ad hoc `local_codex` morning-research automation
(`local_codex/AGENTS.md`, `local_codex/morning_automation.md`). By default,
`MORNING_RESEARCH_STATE_PATH` points at the existing
`local_codex/state/research_digest_state.json` file so `processed_documents`,
`last_successful_run`, and `last_created_notion_page_id` carry over without
any manual migration step. Once you're confident this package has fully
replaced the legacy automation, you can point `MORNING_RESEARCH_STATE_PATH`
at a new location (or leave it as-is indefinitely — it's just a JSON file).

`AGENTS.md` in this package is adapted from `local_codex/AGENTS.md`: the
analyst persona, analytical standards, and output structure are unchanged,
but the Drive-inventory and Notion-page-creation responsibilities have been
moved to the deterministic shell (`drive_pull.py`, `notion_client.py`) —
Codex's job is now analysis and synthesis only, reading from and writing to
its `work_dir`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use `tmp_path` fixtures and mock network-touching modules (`drive_pull`,
`notion_client`, `codex_runner`) — no real Google/Notion/Supabase/Codex calls
are made.
