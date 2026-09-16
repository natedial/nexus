# Distill Tool

Standalone markdown distillation tool for keyword extraction and embeddings.

## What it does

- Splits markdown into page chunks using `--- PAGE N ---` markers.
- Falls back to heading-aware paragraph chunking when page markers are absent, and further refines oversized pages.
- Extracts keywords using a normalized dictionary + RAKE approach.
- Generates local embeddings (sentence-transformers) and writes a `.npz` sidecar.
- Stores chunk metadata and keywords in SQLite for later search pipelines.
- Maintains FTS indexes for fast syntax-based lexical search.
- Supports hybrid querying that fuses keyword/FTS relevance with semantic similarity, duplicate suppression, and deeper candidate recall.

## Page markers

The tool splits pages using this marker pattern by default:

```
--- PAGE 12 ---
```

You can override the regex with `--page-marker-regex`.

## Dictionary format

Provide a domain dictionary as either:
- Plain text file (one term per line, `#` for comments)
- Plain text with aliases using `canonical|alias1|alias2`
- JSON array of strings, or `{"terms": [...]}`, or objects like `{"term": "...", "aliases": ["..."]}`

## CLI usage

```bash
distill --file path/to/input.md --dict path/to/dictionary.txt --out-dir distill_out
```

```bash
cat input.md | distill --dict dictionary.json --out-dir distill_out
```

Skip embeddings (offline smoke test):

```bash
distill --file path/to/input.md --out-dir distill_out --no-embeddings
```

## Run modes

Raw CLI from the local virtualenv:

```bash
source .venv/bin/activate
distill --file path/to/input.md --out-dir distill_out
distill-search --db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "risk controls"
```

Convenience wrappers via `make`:

```bash
make test
make search ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "risk controls"'
```

Containerized via Docker Compose:

```bash
docker compose build app
docker compose run --rm app distill-search \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --query "risk controls"
```

The compose setup bind-mounts the repository into `/app` and keeps Hugging Face caches in a named volume.

Outputs:
- `distill_out/chunks.sqlite` (metadata + keywords)
- `distill_out/embeddings.npz` (vectors + chunk ids)

## Hybrid search CLI

Use the sidecar DB + embeddings for hybrid retrieval:

```bash
distill-search \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --query '"account opening" AND compliance' \
  --limit 10
```

JSON output:

```bash
distill-search --db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "kyc risk" --json
```

Evaluate retrieval on a judged query set:

```bash
distill-search-eval \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --queries eval/queries.jsonl \
  --limit 10
```

Judged queries use JSONL. Each line should contain `query` plus either binary relevance:

```json
{"query_id":"q1","query":"impact on fiscal deficit","relevant":["chunk-a","chunk-b"]}
```

or graded relevance:

```json
{"query_id":"q2","query":"energy prices","relevant":{"chunk-c":2,"chunk-d":1}}
```

Backfill indexes for an existing corpus (no re-distillation):

```bash
distill-backfill --db distill_out/chunks.sqlite --batch-size 2000
```

## Supabase indexing worker

Pull pending documents from Supabase (`parsed_research.parsed_data.full_text`), distill them into
the local corpus, then update `index_status`.

```bash
distill-index-supabase \
  --supabase-url "$SUPABASE_URL" \
  --supabase-key "$SUPABASE_KEY" \
  --out-dir distill_out \
  --poll-limit 50 \
  --index-version v1
```

## Environment

This package reads only variables shared across the pipeline, so it has no
`.env` of its own: `SUPABASE_URL`, `SUPABASE_KEY`, and the optional
`RESEARCH_PROCESSING_ROOT` all come from the repo-root `.env` (see
`../../.env.example`). If this package ever needs its own settings, they belong
in a `packages/research-store/.env` and must be prefixed `RESEARCH_STORE_`.

`distill-index-supabase` loads this package's `.env` (if one exists) and then
the repo-root `.env`. Use `--env-file` to load a specific file instead.

Status behavior:
- Claims work with `index_status='pending'` and moves rows to `processing`.
- Reclaims stale `processing` rows by treating `indexing_batch_id` as a lease timestamp.
- On success sets `index_status='indexed'`, `indexed_at`, and `index_version`.
- On failure sets `index_status='failed'` and writes `index_error`.

Notes:
- Uses local `chunks.sqlite` + `embeddings.npz` as the retrieval corpus.
- Embeddings sidecar is merged incrementally so prior vectors are preserved across runs.

Run continuously for unattended indexing:

```bash
distill-index-supabase \
  --supabase-url "$SUPABASE_URL" \
  --supabase-key "$SUPABASE_KEY" \
  --out-dir distill_out \
  --continuous \
  --poll-limit 25 \
  --poll-interval-seconds 30 \
  --error-backoff-seconds 60 \
  --stale-processing-seconds 3600
```

Docker background worker:

```bash
docker compose up -d indexer
docker compose logs -f indexer
```

### Common flags

- `--file` or `--text` (or pipe via stdin)
- `--dict` path to dictionary
- `--out-dir` output folder (defaults to `distill_out`)
- `--model` embedding model name (default `all-MiniLM-L6-v2`)
- `--overlap-paragraphs` paragraphs of overlap between pages (default `1`)
- `--fallback-target-chars` fallback chunk size target when no page markers (default `2000`)
- `--fallback-min-chars` fallback minimum chunk size before splitting (default `700`)
- `--no-embeddings` skip embedding generation (offline smoke test)
- `distill-search --min-lexical-score` lexical floor for precision (default `0.05`)
- `distill-search --semantic-tail-mode` handling for semantic-only matches: `filter` | `demote` | `allow` (default `filter`)
- `distill-index-supabase --continuous` keep polling until interrupted
- `distill-index-supabase --poll-interval-seconds` sleep between successful cycles (default `30`)
- `distill-index-supabase --error-backoff-seconds` sleep after failed cycles (default `60`)
- `distill-index-supabase --stale-processing-seconds` reclaim stale `processing` leases after this many seconds (default `3600`, use `0` to disable)

## Python usage

```python
from distill_tool import distill_markdown

result = distill_markdown(
    markdown=markdown_text,
    db_path="distill_out/chunks.sqlite",
    npz_path="distill_out/embeddings.npz",
    dictionary_path="dictionary.txt",
)
```

## Output schema

SQLite tables:

- `runs`: one row per distillation run (model, params, source).
- `chunks`: one row per page chunk (page number, text, keywords, hashes).
- `chunk_keywords`: normalized keyword rows (`term`, `source`, `score`) per chunk.
- `chunks_fts`: FTS5 virtual table for syntax-based search across chunk text.
- `keyword_fts`: FTS5 virtual table for fast keyword-expression matching.

Embeddings sidecar:

- `embeddings.npz` contains `chunk_ids` and `embeddings` arrays.

## Notes

- Embeddings require model download on first run (Hugging Face). Use `--no-embeddings` if offline.
- If no page markers are present, fallback chunking groups by paragraphs and also splits oversized single paragraphs using sentence/whitespace boundaries.
