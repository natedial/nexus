# Research Parser

A Python service that watches a Google Drive folder for financial research PDFs, parses them locally, and stores source-grounded artifacts in Supabase PostgreSQL.

Theme and trade extraction belongs in another service. This repo owns parse + durable source storage.

## Features

- **Google Drive Integration**: Polls a folder for new PDFs automatically
- **PDF Parsing**: Local Docling first, optional MinerU CLI fallback
- **Source storage**: Persists markdown artifacts, structured blocks, spans, and retrieval chunks
- **Docker Ready**: Designed to run on Raspberry Pi or any Docker host

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Container (Pi)                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ Drive Watcher│──▶│ PDF Pipeline │──▶│ Supabase Client      │ │
│  │ (polling)    │   │              │   │                      │ │
│  └──────────────┘   └──────────────┘   └──────────────────────┘ │
│         │                  │                                     │
│         ▼                  ▼                                     │
│  ┌──────────────┐                                                   │
│  │ State Store  │                                                   │
│  │ (SQLite)     │                                                   │
│  └──────────────┘                                                   │
└─────────────────────────────────────────────────────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
    Google Drive   Docling / optional MinerU      Supabase PostgreSQL
```

## Processing Pipeline

1. Poll Google Drive for new PDFs
2. Parse locally with Docling (optional MinerU CLI fallback)
3. Strip boilerplate with deterministic rules
4. Identify the house and date from the filename (`YYYY-MM-DD_GS_...`)
5. Store markdown, structured blocks, spans, and retrieval chunks in Supabase

## Quick Start

### 1. Clone and Install

```bash
cd research_parser
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure Environment

Settings load from two files: the repo-root `.env` (shared credentials) first,
then this package's `.env` (parser-owned settings), which wins on conflicts.

```bash
cp ../../.env.example ../../.env   # once per checkout
cp .env.example .env
```

Shared credentials in the repo-root `.env`:

```env
GOOGLE_CREDENTIALS_PATH=./credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
NEXUS_DATABASE_URL=postgresql://nexus:nexus@localhost:5432/nexus
```

Parser-owned settings in `packages/research_parser/.env`, all prefixed
`RESEARCH_PARSER_`:

```env
# Local paths (for development)
RESEARCH_PARSER_STATE_DB_PATH=./data/state.db
RESEARCH_PARSER_ARTIFACT_BASE_DIR=./data/artifacts

# Optional local MinerU fallback after Docling
RESEARCH_PARSER_MINERU_ENABLED=false
RESEARCH_PARSER_MINERU_BIN_PATH=/opt/mineru-venv/bin/mineru

# Catchup on startup (process files from the last N days, 0 disables)
RESEARCH_PARSER_CATCHUP_DAYS=0
```

The unprefixed names (`STATE_DB_PATH`, `CATCHUP_DAYS`, …) are still read as a
deprecated fallback, so existing deployments keep working during migration.

### 3. Set Up Google Drive

1. Create a service account in Google Cloud Console
2. Download the JSON credentials file
3. Share your Google Drive folder with the service account email
4. Set `GOOGLE_DRIVE_FOLDER_ID` to your folder's ID (from the URL)

### 4. Run

```bash
# Run the full service
python -m src.main
```

To run in catchup mode, set `RESEARCH_PARSER_CATCHUP_DAYS` in `.env` before
starting the service:

```bash
# Example: process the last 7 days on startup, then continue polling
export RESEARCH_PARSER_CATCHUP_DAYS=7
python -m src.main
```

Or run with a CLI flag to override the env setting:

```bash
python -m src.main --catchup 7
```

## Optional MinerU Fallback

If you want an additional local parser, install MinerU in a separate virtualenv or via `pipx` and point the service at its CLI binary.

```bash
uv venv /opt/mineru-venv
/opt/mineru-venv/bin/uv pip install -U "mineru[all]"
```

Then configure:

```env
RESEARCH_PARSER_MINERU_ENABLED=true
RESEARCH_PARSER_MINERU_BIN_PATH=/opt/mineru-venv/bin/mineru
RESEARCH_PARSER_MINERU_BACKEND=pipeline
```

The parser order is:

```text
Docling -> optional MinerU CLI
```

## Project Structure

```
research_parser/
├── config/
│   └── boilerplate_rules.yaml
├── src/
│   ├── config.py            # Environment settings
│   ├── pipeline.py          # Parse-and-store orchestrator
│   ├── source.py            # SourceDocument record
│   ├── drive/
│   │   └── watcher.py       # Google Drive polling
│   ├── parser/
│   │   ├── docling_backend.py
│   │   ├── mineru_backend.py
│   │   └── boilerplate.py   # Deterministic disclaimer stripping
│   ├── research_memory/     # Spans + retrieval chunks
│   └── storage/
│       ├── postgres_store.py  # PostgreSQL SourceStore
│       └── state.py           # SQLite state tracking
├── scripts/
│   ├── test_drive.py          # Test Drive connection
│   └── test_full_pipeline.py
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Docker Deployment

### Build and Run

Docker binds the repo-root `credentials/` directory by default (not a package-local
`credentials/` folder).

```bash
mkdir -p data
docker compose up -d
```

### docker-compose.yml

```yaml
version: "3.8"
services:
  research-parser:
    build: .
    restart: unless-stopped
    env_file:
      - path: ../../.env    # shared credentials
        required: false
      - path: .env          # parser-owned settings
        required: false
    volumes:
      - ./data:/app/data              # SQLite state
      - ${GOOGLE_CREDENTIALS_HOST_DIR:-../../credentials}:/app/credentials:ro
      - ./config:/app/config:ro       # Boilerplate rules / optional config
```

### Environment for Docker

Update the env files for Docker paths:

```env
# repo-root .env
GOOGLE_CREDENTIALS_PATH=/app/credentials/service-account.json

# packages/research_parser/.env
RESEARCH_PARSER_STATE_DB_PATH=/app/data/state.db
RESEARCH_PARSER_ARTIFACT_BASE_DIR=/app/data/artifacts
```

## Fault Tolerance

The pipeline is designed to be resilient:

- **Parse is the required step**: without markdown/blocks there is nothing to store
- **Local parsers first**: Docling, then optional MinerU
- **Boilerplate safeguard**: deterministic stripping from `config/boilerplate_rules.yaml`
- **Span writes fail closed**: memory-table failures fail the storage step
- **Reparse preserves downstream work**: upserts omit `theme_count`, `trade_count`, and index columns
- **State tracking**: SQLite tracks processed files to avoid reprocessing

## Checking Progress (SQLite)

The SQLite state database tracks each processed file and the status of every step.

```bash
# Status counts
sqlite3 ./data/state.db "SELECT status, COUNT(*) FROM processed_files GROUP BY status;"

# Latest 20 files with step flags
sqlite3 ./data/state.db "SELECT file_name, status, parse_ok, boilerplate_ok, storage_ok, updated_at FROM processed_files ORDER BY updated_at DESC LIMIT 20;"
```

Each document stores parse artifacts and source spans. `parsed_data` is the source payload:

```json
{
  "full_text": "Rates Outlook\n\nDuration should rally if payrolls cool.",
  "identity": {
    "document_id": "drive-gs",
    "document_uri": "gdrive://drive-gs",
    "source": "Goldman Sachs",
    "source_date": "2026-08-31"
  },
  "parse": {
    "backend": "docling",
    "parser_version": "parser-source-v1"
  }
}
```

## Development

### Run Tests

```bash
python3 -m pytest tests/
python scripts/test_drive.py
```

## Troubleshooting

### "No PDFs found in folder"

- Ensure the folder is shared with your service account email
- Check the folder ID is correct (from the Drive URL)

## License

MIT
