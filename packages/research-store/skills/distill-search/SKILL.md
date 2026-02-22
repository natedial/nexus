---
name: distill-search
description: Query and calibrate the local hybrid retrieval tool `distill-search` over distilled corpora (`chunks.sqlite` + `embeddings.npz`). Use for semantic/lexical search execution, ranking-quality tuning, precision-vs-recall adjustment, and troubleshooting fallback behavior when semantic embeddings are unavailable.
---

# Distill Search

## Run Query

1. Work from the repository root.
2. Source the virtual environment before running commands.
3. Run `distill-search` with DB, embeddings sidecar, query, and limit.

```bash
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz --query "impact on fiscal deficit" --limit 5
```

## Use Score Controls

Tune these flags intentionally:

- `--keyword-weight` and `--semantic-weight`: Set lexical vs semantic contribution.
- `--min-lexical-score`: Apply lexical floor (default `0.05`) to demote weak lexical hits.
- `--semantic-tail-mode`: Handle semantic-only matches when lexical signal exists.
- `--semantic-tail-penalty`: Apply demotion factor when `--semantic-tail-mode demote`.

## Apply Presets

Use one of these patterns first, then iterate:

```bash
# High precision (default tail filtering, stricter lexical floor)
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz \
  --query "impact on fiscal deficit" --limit 10 \
  --keyword-weight 0.65 --semantic-weight 0.35 \
  --min-lexical-score 0.08 --semantic-tail-mode filter
```

```bash
# Balanced (project defaults)
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz \
  --query "impact on fiscal deficit" --limit 10
```

```bash
# High recall (allow semantic tail)
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz \
  --query "impact on fiscal deficit" --limit 10 \
  --keyword-weight 0.4 --semantic-weight 0.6 \
  --min-lexical-score 0 --semantic-tail-mode allow
```

## Debug Retrieval

- Run lexical-only for diagnostics:

```bash
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz \
  --query "impact on fiscal deficit" --semantic-weight 0 --limit 10
```

- Use JSON output for structured comparison across parameter sweeps:

```bash
source .venv/bin/activate
distill-search --db data/chunks.sqlite --npz data/embeddings.npz \
  --query "impact on fiscal deficit" --limit 10 --json
```

## Interpret Output

- `lexical=0.000` with positive semantic score indicates semantic-only retrieval.
- `semantic=0.000` indicates lexical-only result or semantic fallback.
- Warning about semantic unavailability indicates the tool fell back to lexical ranking.
