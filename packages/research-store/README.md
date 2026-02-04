# Distill Tool

Standalone markdown distillation tool for keyword extraction and embeddings.

## What it does

- Splits markdown into page chunks using `--- PAGE N ---` markers.
- Extracts keywords using a hybrid dictionary + RAKE approach.
- Generates local embeddings (sentence-transformers) and writes a `.npz` sidecar.
- Stores chunk metadata and keywords in SQLite for later search pipelines.

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

Embeddings sidecar:

- `embeddings.npz` contains `chunk_ids` and `embeddings` arrays.

## Notes

- Embeddings require model download on first run (Hugging Face). Use `--no-embeddings` if offline.
- If no page markers are present, the entire document becomes one chunk.
