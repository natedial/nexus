# Research Gleaner

Research Gleaner captures deliberately selected excerpts and preserves enough
source context to route them into the Nexus pipeline later. The first slice
supports colored text in Notion and native PDF highlights from reMarkable, and
writes inspectable JSON capture batches.

This package owns capture and routing state. It does not analyze excerpts,
persist canonical research records, render briefings, or deliver messages.

## Install

```bash
cd packages/research_gleaner
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ../research_pipeline_ops
python3 -m pip install -e ".[dev]"
```

Set the current Notion data source ID, not the parent database ID:

```bash
export NOTION_TOKEN="..."
export RESEARCH_GLEANER_NOTION_DATA_SOURCE_ID="..."
```

The integration needs read access to the data source and its pages.

## Capture From Notion

```bash
research-gleaner notion \
  --topic Markets \
  --resource-type "Research Note" \
  --resource-type Commentary \
  --since 24h
```

By default every captured excerpt has the intent `hold`. Routing is explicit:

```bash
research-gleaner notion \
  --route yellow=research \
  --route blue=research \
  --route green=relay
```

Valid intents are `hold`, `research`, `relay`, and `both`. This command only
records the requested intent; downstream delivery adapters are intentionally
not part of the first slice.

`source_style` records the exact source color and is never interpreted as a
permanent semantic category. Routing rules may change without changing capture
identity or rewriting the observed source evidence.

Default paths:

- state: `~/.local/state/research-gleaner/gleaner.db`
- output: `~/research-gleaner/out/<timestamp>-notion-captures.json`

Override them with `--state-db`, `--out`, or the environment variables shown
in `.env.example`.

`NOTION_TOKEN` is an account-level credential and therefore belongs in the
repo-root `.env`. The data source ID and local paths belong in this package's
`.env`. Gleaner loads both files using the standard Nexus precedence rules.

The package `.env` also owns the scheduled sweep profile:

```env
RESEARCH_GLEANER_NOTION_TOPIC=Markets
RESEARCH_GLEANER_NOTION_RESOURCE_TYPES=Research Note,Commentary
RESEARCH_GLEANER_NOTION_SINCE=24h
```

## Daily LaunchAgent

The source-specific runners and LaunchAgent definitions are:

- `scripts/run-notion-sweep.sh`
- `launchd/com.researchgleaner.notion-sweep.plist`
- `scripts/run-remarkable-sweep.sh`
- `launchd/com.researchgleaner.remarkable-sweep.plist`

The Notion LaunchAgent runs every calendar day at 4:00 AM in the Mac's local
time. The reMarkable LaunchAgent runs at 4:10 AM to avoid simultaneous writes
to the shared SQLite database. Both write timestamped JSON batches to
`RESEARCH_GLEANER_OUTPUT_DIR`; SQLite records which captures are new across
runs. Source-specific non-blocking file locks make overlapping invocations exit
successfully without starting another sweep.

Install after the package venv, root `NOTION_TOKEN`, and package data source ID
are configured:

```bash
mkdir -p ~/Library/LaunchAgents ~/Library/Logs/research-gleaner
cp launchd/com.researchgleaner.notion-sweep.plist ~/Library/LaunchAgents/
cp launchd/com.researchgleaner.remarkable-sweep.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.researchgleaner.notion-sweep.plist
plutil -lint ~/Library/LaunchAgents/com.researchgleaner.remarkable-sweep.plist
launchctl bootout "gui/$UID" \
  ~/Library/LaunchAgents/com.researchgleaner.notion-sweep.plist 2>/dev/null || true
launchctl bootout "gui/$UID" \
  ~/Library/LaunchAgents/com.researchgleaner.remarkable-sweep.plist 2>/dev/null || true
launchctl bootstrap "gui/$UID" \
  ~/Library/LaunchAgents/com.researchgleaner.notion-sweep.plist
launchctl bootstrap "gui/$UID" \
  ~/Library/LaunchAgents/com.researchgleaner.remarkable-sweep.plist
```

Run the same sweep immediately and inspect its status:

```bash
launchctl kickstart -k "gui/$UID/com.researchgleaner.notion-sweep"
launchctl kickstart -k "gui/$UID/com.researchgleaner.remarkable-sweep"
launchctl print "gui/$UID/com.researchgleaner.notion-sweep"
launchctl print "gui/$UID/com.researchgleaner.remarkable-sweep"
tail -n 50 ~/Library/Logs/research-gleaner/notion-sweep.{out,err}.log
tail -n 50 ~/Library/Logs/research-gleaner/remarkable-sweep.{out,err}.log
```

Changing the package `.env` does not require reloading the LaunchAgent. Changes
to the plist do.

## Capture From reMarkable

Register the open-source `remarkable-mcp` client once. Its cloud credential is
stored in `~/.rmapi`, outside the repository:

```bash
uvx remarkable-mcp --register <one-time-code>
```

Then run a metadata-first sweep:

```bash
research-gleaner remarkable --since 24h
```

The sweep lists document metadata, filters to recently modified revisions, and
downloads only changed PDFs. It reads native reMarkable `GlyphRange`
annotations from the document archive, so neither PDF rendering nor OCR is
needed. A successfully processed revision is recorded in SQLite and will not
be downloaded again unless reMarkable reports a new revision.

The tablet's annotation color is preserved verbatim as `source_style`. It has
no fixed semantic meaning. Optional routing changes only mutable `intent`:

```bash
research-gleaner remarkable \
  --route pink=research \
  --route yellow=relay
```

Current reMarkable highlighter RGBA overrides are recorded with human-readable
source styles: `yellow`, `blue`, `pink`, `orange`, and `green`. Every capture
also retains the raw color enum, numeric ID, and RGBA tuple in metadata. Unknown
RGBA values remain lossless as `rgba-R-G-B-A` rather than being guessed.

The default lookback is 24 hours. Override it with `--since` or
`RESEARCH_GLEANER_REMARKABLE_SINCE`. Documents outside that window are left
untouched, which prevents a first run from downloading the tablet's full PDF
library. The scheduled profile uses a 48-hour overlap so a missed run does not
lose a changed document; revision deduplication prevents repeat downloads.

## Contract

Each capture contains:

- stable `capture_id`
- source document identity and URI
- exact selected text and surrounding block text
- heading path
- a source-specific locator
- original source style
- mutable routing intent, stored separately from source style
- source and capture timestamps

The SQLite store deduplicates captures across runs and separately tracks
delivery status per destination.

## Query Captures

The query command returns structured JSON and does not require source
credentials:

```bash
research-gleaner query --text "dealer inventory" --compact
research-gleaner query --source-style pink --since 7d --compact
research-gleaner query --source-kind remarkable --document "OAT Dealers"
research-gleaner query --source-kind notion --document "Rates"
research-gleaner query --intent research --limit 20
```

Filters can be combined. Full-text terms are AND-combined. `--since` filters
the first time Gleaner ingested a capture. Current captures are returned by
default; use `--include-inactive` to include highlights later removed from a
source document. Use `--compact` for first-pass agent searches and omit it when
the complete context and source metadata are needed.

The store keeps query-critical fields as indexed columns and the complete,
lossless capture as JSON. It also tracks source-document revisions so an
adapter can skip unchanged documents and reconcile removed highlights after a
successful extraction.

The agent query skill lives at `skills/gleaner-query`. Its canonical source is
versioned with this package and can be installed into `~/.codex/skills` for
automatic discovery.

## Tests

```bash
python3 -m pytest
```
