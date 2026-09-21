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

This is a Python service that watches a Google Drive folder for financial research PDFs, parses them locally, and stores source-grounded artifacts in Supabase PostgreSQL.

Theme and trade extraction belongs in a separate service. This repo owns parse + durable source storage.

### Processing Pipeline

The pipeline (`src/pipeline.py`) orchestrates this flow:

1. **Drive Watcher** → polls Google Drive folder for new PDFs
2. **Parser backends** → Docling digital text first (`do_ocr=False`). If the digital pass is gappy (missing PDF pages, thin text-per-page, stub figure captions, or `FALLBACK`), retry Docling with OCR (`EasyOcrOptions(force_full_page_ocr=False)`). Keep OCR only if it gains ≥15% text or +0.05 confidence. Optional MinerU CLI last if still `FALLBACK`. Set `RESEARCH_PARSER_DOCLING_OCR_RETRY=false` to disable the OCR branch.
3. **Deterministic clean** → filename identity (`YYYY-MM-DD_GS_...`) + boilerplate rules (refuses cuts that remove more than `max_strip_fraction` unless confidence is high)
4. **Source artifacts** → `document.md`, `blocks.jsonl`, `figures.jsonl`, `clean_text.md`
5. **Supabase storage** → upsert `parsed_research` plus `research_document_artifacts`, `research_spans`, and `research_retrieval_chunks`

Span writes fail closed: a memory-table failure fails the storage step.

### Fault Tolerance Design

- PDF parsing failure is fatal (no content to process)
- Boilerplate stripping falls back to raw markdown
- Partial parse artifacts can resume without re-downloading when `parse_ok` and `clean_text.md` exist. `scripts/test_full_pipeline.py --force` skips that resume and re-parses.
- State DB tracks parse / boilerplate / storage success
- Parse-only upserts do not wipe downstream `research_themes` or index columns

### State Management

SQLite database (`src/storage/state.py`) tracks:
- Which files have been processed (idempotency)
- Per-step success/failure for debugging
- Processing status: pending, parsing, storing, completed, partial, failed
- Legacy `extracting` rows remain retryable

### Configuration

All settings via environment variables, loaded through pydantic-settings (`src/config.py`) from the repo-root `.env` first and this package's `.env` second.

Required vars (shared, unprefixed, set at the repo root):
- `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_DRIVE_FOLDER_ID`
- `NEXUS_DATABASE_URL`

Parser-owned settings are prefixed `RESEARCH_PARSER_` and live in `packages/research_parser/.env`. The unprefixed forms remain a deprecated fallback.
