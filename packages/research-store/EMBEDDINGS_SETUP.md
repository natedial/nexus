# Embeddings Setup And Integration Guide

This guide is for running the semantic/hybrid pipeline once you are back on a network with internet access (for model download).

## 1. Clone And Enter Repo

```bash
git clone <your-repo-url> research-store
cd research-store
```

## 2. Create Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
```

Notes:
- `sentence-transformers` is required for embeddings.
- First model use downloads from Hugging Face, so do this on home network.

## 3. Warm The Embedding Model (one-time)

This forces the initial model download and local cache.

```bash
python - <<'PY'
from distill_tool.embeddings import EmbeddingConfig, EmbeddingModel
model = EmbeddingModel(EmbeddingConfig(model_name="all-MiniLM-L6-v2"))
print(model.embed(["model warmup"]).shape)
PY
```

Expected output shape is `(1, 384)` for `all-MiniLM-L6-v2`.

## 4. Distill With Embeddings Enabled

Do not pass `--no-embeddings`.

```bash
distill \
  --file path/to/your_input.md \
  --dict path/to/your_dictionary.txt \
  --out-dir distill_out \
  --model all-MiniLM-L6-v2
```

If documents do not contain explicit page markers, fallback paragraph chunking is used automatically.
You can tune it:

```bash
distill \
  --file path/to/your_input.md \
  --dict path/to/your_dictionary.txt \
  --out-dir distill_out \
  --fallback-target-chars 2000 \
  --fallback-min-chars 700
```

Output files:
- `distill_out/chunks.sqlite`
- `distill_out/embeddings.npz`

## 5. If DB Already Exists, Backfill Search Indexes

If you have an older DB or want to ensure indexes are rebuilt:

```bash
distill-backfill --db distill_out/chunks.sqlite --batch-size 2000
```

This rebuilds:
- `chunk_keywords`
- `chunks_fts`
- `keyword_fts`

## 6. Run Hybrid Query (Keyword + Syntax + Semantic)

```bash
distill-search \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --query '"risk controls" AND governance' \
  --limit 10
```

Tune fusion weights if needed:

```bash
distill-search \
  --db distill_out/chunks.sqlite \
  --npz distill_out/embeddings.npz \
  --query "topic exploration query" \
  --keyword-weight 0.45 \
  --semantic-weight 0.55
```

## 7. Quick Health Checks

Check DB tables:

```bash
sqlite3 distill_out/chunks.sqlite ".tables"
```

Verify embeddings file has vectors:

```bash
python - <<'PY'
import numpy as np
d = np.load("distill_out/embeddings.npz")
print("chunk_ids:", d["chunk_ids"].shape)
print("embeddings:", d["embeddings"].shape)
PY
```

## 8. Common Failure Modes

- `RuntimeError: sentence-transformers is required`
  - Run `pip install -e .` (or `pip install sentence-transformers`).

- Empty semantic scores
  - Ensure you did not run distill with `--no-embeddings`.
  - Ensure `--npz` points to the matching embeddings file for that DB.

- Model download fails
  - Retry on home network and re-run step 3.

- Search only returns lexical behavior
  - Semantic fallback is automatic when embeddings are missing/empty.
  - Confirm `embeddings.npz` exists and contains non-zero width vectors.
