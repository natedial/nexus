# Distill Tool Docs

## Scope

This tool distills markdown into:
- page-level chunks
- extracted keywords
- local embeddings
- SQLite metadata + `.npz` embeddings sidecar

It is designed for offline processing; search is handled elsewhere.

## Page markers

Default page marker pattern:

```
--- PAGE 12 ---
```

If no markers exist, the entire markdown becomes one chunk.

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

## Future extensions

- Pluggable embedding backends (remote APIs, alternative local models)
- Optional vector DB targets
- Chunking strategies beyond page-level (section, paragraph)
