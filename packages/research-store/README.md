# Distill Tool

Standalone markdown distillation tool for keyword extraction and embeddings.

## What it does

- Splits markdown into page chunks using `--- PAGE N ---` markers.
- Extracts keywords using a hybrid dictionary + RAKE approach.
- Generates local embeddings (sentence-transformers) and writes a `.npz` sidecar.
- Stores chunk metadata and keywords in SQLite for later search pipelines.
- Maintains FTS indexes for fast syntax-based lexical search.
- Supports hybrid querying that fuses keyword/FTS relevance with semantic similarity.

## Page markers

The tool splits pages using this marker pattern by default:

```
--- PAGE 12 ---
```

You can override the regex with `--page-marker-regex`.

## Dictionary format

Provide a domain dictionary as either:
- Plain text file (one term per line, `#` for comments)
- JSON array of strings (or `{"terms": [...]}`)

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

Backfill indexes for an existing corpus (no re-distillation):

```bash
distill-backfill --db distill_out/chunks.sqlite --batch-size 2000
```

### Common flags

- `--file` or `--text` (or pipe via stdin)
- `--dict` path to dictionary
- `--out-dir` output folder (defaults to `distill_out`)
- `--model` embedding model name (default `all-MiniLM-L6-v2`)
- `--overlap-paragraphs` paragraphs of overlap between pages (default `1`)
- `--no-embeddings` skip embedding generation (offline smoke test)

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
- If no page markers are present, the entire document becomes one chunk.
