# Distill Tool Docs

## Scope

This tool distills markdown into:
- page-level chunks
- extracted keywords
- local embeddings
- SQLite metadata + `.npz` embeddings sidecar

It is designed for offline processing and local hybrid retrieval.

## Page markers

Default page marker pattern:

```
--- PAGE 12 ---
```

If no markers exist, fallback paragraph-based chunking is applied.
Markdown headings are preserved as section context during fallback chunking.
Oversized single paragraphs are further split by sentence boundaries (with whitespace fallback).

## CLI

```bash
distill --file path/to/input.md --dict path/to/dictionary.txt --out-dir distill_out
```

```bash
cat input.md | distill --dict dictionary.json --out-dir distill_out
```

Offline smoke test (no model download):

```bash
distill --file path/to/input.md --out-dir distill_out --no-embeddings
```

Convenience wrappers:

```bash
make test
make search ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "risk controls"'
```

Docker Compose:

```bash
docker compose build app
docker compose run --rm app distill-search \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --query "risk controls"
```

## Python API

```python
from distill_tool import distill_markdown, distill_file

result = distill_markdown(
    markdown=markdown_text,
    db_path="distill_out/chunks.sqlite",
    npz_path="distill_out/embeddings.npz",
    dictionary_path="dictionary.txt",
)
```

## Output

SQLite:
- `runs` table records one row per run with params and model info.
- `chunks` table records one row per page chunk.

`.npz` sidecar:
- `chunk_ids`: array of chunk ids
- `embeddings`: array of vectors aligned with `chunk_ids`

FTS virtual tables:
- `chunks_fts`: full text index over chunk text (`MATCH` syntax supported).
- `keyword_fts`: keyword phrase index for fast lexical filtering.

## Schema details

`runs`:
- `run_id` (TEXT, PK)
- `created_at` (TEXT, SQLite datetime)
- `model_name` (TEXT)
- `embedding_dim` (INTEGER)
- `source` (TEXT) file path or `inline`
- `dictionary_path` (TEXT, nullable)
- `params_json` (TEXT, JSON)

`chunks`:
- `chunk_id` (TEXT, PK)
- `run_id` (TEXT, FK -> runs)
- `source_path` (TEXT, nullable)
- `page_number` (INTEGER)
- `chunk_index` (INTEGER)
- `text` (TEXT)
- `keywords_json` (TEXT, JSON)
- `text_hash` (TEXT)
- `created_at` (TEXT, SQLite datetime)

`chunk_keywords`:
- `chunk_id` (TEXT, FK -> chunks)
- `term` (TEXT)
- `source` (TEXT) dictionary | rake
- `score` (REAL)

## Keyword extraction

Hybrid approach:
- normalized dictionary matches with optional aliases
- RAKE-style phrase scoring for additional phrases

Dictionary format:
- text file: one term per line (`#` for comments)
- text file with aliases via `canonical|alias1|alias2`
- JSON: array of strings, `{"terms":[...]}`, or objects containing `term` and `aliases`

## Embeddings

Default model: `all-MiniLM-L6-v2`

To change models, pass `--model` or `model_name=...` in Python.

## Hybrid search

Use CLI:

```bash
distill-search --db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query '"risk controls" AND audit'
```

Evaluate retrieval quality:

```bash
distill-search-eval \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --queries eval/queries.jsonl \
  --limit 10
```

This ranks by:
- lexical score from `chunks_fts` + normalized `chunk_keywords`
- semantic score from cosine similarity over embeddings
- reciprocal-rank fusion with weighted lexical/semantic priors
- duplicate-aware downranking using `text_hash`
- lexical precision floor (`--min-lexical-score`, default `0.05`)
- semantic-only tail handling (`--semantic-tail-mode`: `filter` | `demote` | `allow`)

Judged query JSONL supports:
- binary relevance with `{"relevant":["chunk-a","chunk-b"]}`
- graded relevance with `{"relevant":{"chunk-a":2,"chunk-b":1}}`

Backfill an existing DB:

```bash
distill-backfill --db distill_out/chunks.sqlite --batch-size 2000
```

## Supabase indexing

Index rows from Supabase where `index_status='pending'` by reading
`parsed_data.full_text` and updating row status after processing.

```bash
distill-index-supabase \
  --supabase-url "$SUPABASE_URL" \
  --supabase-key "$SUPABASE_KEY" \
  --out-dir distill_out \
  --poll-limit 50 \
  --index-version v1
```

The command loads `.env` by default. Override with `--env-file path/to/.env`.

## Future extensions

- Pluggable embedding backends (remote APIs, alternative local models)
- Optional vector DB targets
- Chunking strategies beyond page-level (section, paragraph)
