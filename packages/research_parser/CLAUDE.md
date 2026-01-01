# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands

```bash
# Install dependencies
pip install -e .

# Run the service
python -m src.main

# Run with Docker
docker compose build
docker compose up -d

# View logs
docker compose logs -f

# Development mode (with source mounting)
docker compose --profile dev up
```

## Architecture

This is a Python service that watches a Google Drive folder for financial research PDFs, extracts structured data using LLMs, and stores results in Supabase PostgreSQL.

### Processing Pipeline

The pipeline (`src/pipeline.py`) orchestrates this flow:

1. **Drive Watcher** → polls Google Drive folder for new PDFs
2. **LlamaIndex Parser** → uploads PDF to LlamaIndex Cloud, retrieves markdown
3. **Extraction Chain** (sequential, fault-tolerant):
   - Strip boilerplate (Claude Haiku) → remove legal disclaimers
   - Extract metadata (Claude Haiku) → source, date, region, asset focus
   - Extract themes (Claude Sonnet) → 3-6 key themes with excerpts
   - Extract trades (Claude Sonnet) → explicit trade recommendations
   - Synthesize through-lines (Claude Sonnet) → combine themes/trades into narratives
4. **Supabase Storage** → insert `parsed_research` record

### Fault Tolerance Design

Each extraction step is wrapped in try/except. If a step fails:
- Processing continues with defaults/empty values
- Partial results are still stored
- State DB tracks which steps succeeded/failed
- Only PDF parsing failure is fatal (no content to process)

### State Management

SQLite database (`src/storage/state.py`) tracks:
- Which files have been processed (idempotency)
- Per-step success/failure for debugging
- Processing status: pending, parsing, extracting, completed, partial, failed

### Configuration

All settings via environment variables, loaded through pydantic-settings (`src/config.py`). Required vars:
- `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_DRIVE_FOLDER_ID`
- `ANTHROPIC_API_KEY`, `LLAMAINDEX_API_KEY`
- `SUPABASE_URL`, `SUPABASE_KEY`

### Prompts

All LLM prompts are in `src/extraction/prompts.py`, ported from an n8n workflow. These are carefully crafted for financial research extraction—modify with care.
