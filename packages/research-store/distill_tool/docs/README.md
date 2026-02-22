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
- dictionary matches (case-insensitive)
- RAKE-style phrase scoring for additional phrases

Dictionary format:
- text file: one term per line (`#` for comments)
- JSON: array of strings, or `{"terms":[...]}`

## Embeddings

Default model: `all-MiniLM-L6-v2`

To change models, pass `--model` or `model_name=...` in Python.

## Hybrid search

Use CLI:

```bash
distill-search --db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query '"risk controls" AND audit'
```

This ranks by:
- lexical score from `chunks_fts` + `keyword_fts`
- semantic score from cosine similarity over embeddings
- weighted fusion (`--keyword-weight`, `--semantic-weight`)
- lexical precision floor (`--min-lexical-score`, default `0.05`)
- semantic-only tail handling (`--semantic-tail-mode`: `filter` | `demote` | `allow`)

Backfill an existing DB:

```bash
distill-backfill --db distill_out/chunks.sqlite --batch-size 2000
```

## Future extensions

- Pluggable embedding backends (remote APIs, alternative local models)
- Optional vector DB targets
- Chunking strategies beyond page-level (section, paragraph)
