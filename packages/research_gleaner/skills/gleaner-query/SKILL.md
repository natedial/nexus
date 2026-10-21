---
name: gleaner-query
description: Query source-grounded highlights captured by Nexus Research Gleaner. Use when an agent needs to find, filter, inspect, or summarize stored excerpts by source, document, text, source style, routing intent, or ingestion time.
---

# Gleaner Query

Use the supported JSON query interface rather than opening the SQLite database directly. Run commands from `/Users/ncdial/devwork/nexus/packages/research_gleaner`:

```bash
.venv/bin/research-gleaner query
```

Combine filters as needed:

```bash
# Full-text terms; all terms must match.
.venv/bin/research-gleaner query --text "dealer inventory" --compact

# Exact recorded source style or color.
.venv/bin/research-gleaner query --source-style pink --compact

# Source, document-title substring, and first-ingestion lookback.
.venv/bin/research-gleaner query --source-kind notion --document "Rates" --since 7d --compact

# Native PDF highlights captured from reMarkable.
.venv/bin/research-gleaner query --source-kind remarkable --document "OAT Dealers" --compact

# Explicit downstream routing state.
.venv/bin/research-gleaner query --intent research --limit 20 --compact
```

The package `.env` selects the state database. Use `--state-db PATH` only when the user identifies another database.

## Interpretation

- Treat `source_style` as immutable source evidence. Never infer a fixed meaning for a color; routing conventions may change.
- Treat `intent` as mutable workflow state, not source meaning.
- Results include the indexed fields and a lossless `payload` containing document metadata, locator, context, and source-specific metadata.
- Use `--compact` for discovery. Rerun without it when full context or metadata is required.
- Queries return active captures by default. Add `--include-inactive` only for historical or deletion/reconciliation questions.
- `--since` filters when Gleaner first ingested the capture, not when the source document was authored or modified.

When answering from captures, preserve the document title and page or block locator when available. Distinguish quoted source evidence from any analysis you add.
