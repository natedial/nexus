# Agentic Retrieval API Design

**Date:** 2026-03-15
**Status:** Approved
**Scope:** Add a programmatic API surface and date-range filtering to `distill_tool` so LLM agents can use the search engine as a retrieval primitive.

## Problem

The distill tool's hybrid search engine is designed for human-invoked CLI queries. Agents need to answer complex, multi-dimensional analytical questions (e.g., "what was the consensus on CPI in January 2025 and how did that relate to Fed cut expectations?"). These queries require:

- **Query decomposition**: breaking a complex question into targeted sub-queries
- **Temporal scoping**: narrowing results to specific date windows
- **Multi-sweep retrieval**: calling search multiple times and synthesizing results

The agent handles all reasoning and synthesis. The tool's job is to be a fast, reliable, filterable retrieval primitive.

## Design Principles

1. **The tool stays dumb.** All query decomposition and synthesis logic lives in the agent, not in this codebase.
2. **Minimal surface area.** Expose only the parameters an agent needs (query, dates, limit). Hide scoring internals (weights, RRF k, tail modes).
3. **Date filtering is the key new capability.** The `source_date` column already exists in the schema — search just doesn't filter on it yet.
4. **No new dependencies.** Everything uses existing stdlib and numpy.

## Architecture

```
[LLM Agent]
    |
    |-- calls corpus_info() once to discover date range & sources
    |
    |-- calls search() N times with targeted sub-queries
    |       |
    |       v
    |   [api.py] -- thin wrapper
    |       |
    |       v
    |   [HybridSearchEngine.search()] -- with date_from/date_to filtering
    |       |
    |       +-- lexical scoring (FTS + keywords, date-filtered SQL)
    |       +-- semantic scoring (embeddings, date-filtered mask)
    |       +-- RRF fusion, dedup, ranking
    |       |
    |       v
    |   list[dict] -- plain serializable results
    |
    |-- synthesizes answer from combined results
```

## Change 1: Date-Range Filtering in `HybridSearchEngine`

### File: `distill_tool/search.py`

**New parameters on `search()`:**

```python
def search(
    self,
    query: str,
    limit: int = 10,
    run_id: str | None = None,
    date_from: str | None = None,   # ISO date string, inclusive
    date_to: str | None = None,     # ISO date string, inclusive
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
    min_lexical_score: float = 0.05,
    semantic_tail_mode: str = "filter",
    semantic_tail_penalty: float = 0.25,
) -> list[SearchResult]:
```

**New helper method:**

```python
def _chunk_ids_for_date_range(
    self, date_from: str | None, date_to: str | None
) -> set[str] | None:
    """Return chunk IDs within the date range, or None if no filtering needed.

    Chunks with NULL source_date are excluded from date-filtered queries.
    This is intentional: if the agent asks for a date window, undated
    chunks are not relevant to that window.
    """
    if date_from is None and date_to is None:
        return None
    sql = "SELECT chunk_id FROM chunks WHERE source_date IS NOT NULL"
    params: list[str] = []
    if date_from is not None:
        sql += " AND source_date >= ?"
        params.append(date_from)
    if date_to is not None:
        sql += " AND source_date <= ?"
        params.append(date_to)
    with sqlite3.connect(self.db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return {str(row[0]) for row in rows}
```

**Filtering approach — set intersection, not SQL threading:**

The `search()` method computes the allowed chunk_id set once via `_chunk_ids_for_date_range()`, then applies it uniformly to both scoring paths:

1. **Lexical path**: `_lexical_scores()` (which internally calls `_fts_query()` and `_keyword_scores()`) runs unchanged — no SQL modifications. After it returns its `dict[str, float]`, `search()` intersects the result keys with the allowed set.

2. **Semantic path**: `_semantic_scores()` already accepts a `run_id` filter that works via an in-memory mask. It gains an optional `allowed_chunk_ids: set[str] | None` parameter. When provided, this set is intersected with any `run_id` mask to produce the final embedding matrix mask.

3. **Combined filtering**: When both `run_id` and date range are specified, `search()` intersects `_chunk_ids_for_run(run_id)` with `_chunk_ids_for_date_range(date_from, date_to)` to produce a single allowed set passed to both paths.

This approach is less invasive than threading date predicates through `_lexical_scores()` → `_fts_query()` / `_keyword_scores()`, and it keeps the filtering logic in one place.

**Call chain:**
```
search(date_from, date_to)
  ├── _chunk_ids_for_date_range() → allowed_ids (or None)
  ├── _lexical_scores() → scores  (unchanged internally)
  │     ├── _fts_query()           (unchanged)
  │     └── _keyword_scores()      (unchanged)
  ├── intersect lexical scores with allowed_ids
  ├── _semantic_scores(allowed_chunk_ids=allowed_ids)  → scores
  └── RRF fusion on filtered candidates only
```

**Pre-filtering, not post-filtering.** Date constraints are applied at the candidate-generation stage, before RRF scoring. This ensures ranks are computed over the date-relevant subset only, producing internally consistent scores. Lexical results are intersected before rank computation.

**NULL `source_date` behavior.** Chunks with `NULL` `source_date` are excluded from date-filtered queries. This is the correct behavior: when the agent asks for "January 2025", undated chunks have no temporal relevance. When no date filter is specified (`date_from=None, date_to=None`), all chunks (including undated) are searched as before.

**SQLite ISO string comparison.** The `source_date` column stores ISO date strings. SQLite string comparison sorts ISO dates correctly (`'2025-01-15' < '2025-02-01'`), so no date parsing is needed at query time.

### File: `distill_tool/storage.py`

**Add index on `source_date`** in `init_db()`:

```python
conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_source_date
    ON chunks(source_date)
    """
)
```

This supports the `_chunk_ids_for_date_range()` query efficiently as the corpus grows.

## Change 2: Agent-Facing API Module

### File: `distill_tool/api.py` (new)

Two functions, both stateless:

```python
def search(
    query: str,
    *,
    db_path: str,
    npz_path: str | None = None,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    run_id: str | None = None,
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
) -> list[dict]:
    """Search the distilled research corpus.

    Returns list of dicts with keys:
        chunk_id, source_path, source_date, page_number,
        text, keywords, lexical_score, semantic_score, hybrid_score
    """
```

```python
def corpus_info(db_path: str) -> dict:
    """Return metadata about the corpus.

    Returns dict with keys:
        total_chunks (int), total_runs (int),
        date_range (dict with min/max or null),
        sources (list of distinct source_path strings)
    """
```

**Input validation:**

`api.search()` validates `date_from` and `date_to` format before passing to the engine:

```python
import re
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _validate_date(value: str | None, name: str) -> None:
    if value is not None and not _ISO_DATE_RE.match(value):
        raise ValueError(f"{name} must be ISO format YYYY-MM-DD, got: {value!r}")
```

This catches malformed dates from the agent (e.g., "January 2025", "2025/01/01") early, before they silently produce wrong results via SQLite string comparison.

**`corpus_info()` implementation:**

```python
def corpus_info(db_path: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        date_row = conn.execute(
            "SELECT MIN(source_date), MAX(source_date) FROM chunks WHERE source_date IS NOT NULL"
        ).fetchone()
        sources = [
            row[0] for row in
            conn.execute("SELECT DISTINCT source_path FROM chunks WHERE source_path IS NOT NULL").fetchall()
        ]
    return {
        "total_chunks": total_chunks,
        "total_runs": total_runs,
        "date_range": {"min": date_row[0], "max": date_row[1]} if date_row[0] else None,
        "sources": sources,
    }
```

`MIN`/`MAX` ignore NULLs. If all chunks have `NULL` `source_date`, `date_range` returns `None`. The agent sees this and knows date filtering won't help.

**Design decisions:**

- **Stateless per call.** Each `search()` creates a `HybridSearchEngine` instance. Engine init loads the NPZ (numpy file read, ~50ms typical). The SentenceTransformer model is lazy-loaded only on first semantic query. Acceptable for agent tool-call cadence.
- **No engine caching.** YAGNI. Agent makes a handful of calls per reasoning turn, not thousands. If usage patterns change, engine reuse (singleton or LRU cache keyed on db_path+npz_path) is the first optimization target.
- **Returns plain dicts.** Directly JSON-serializable. No dataclasses in the wire format.
- **Strips internal fields.** `run_id` and `chunk_index` are omitted from the return — these are storage implementation details the agent doesn't need. Keeps `source_path`, `source_date`, `page_number`, `keywords` for provenance reasoning.
- **`keyword_weight` / `semantic_weight` in the Python signature** exist for programmatic callers (testing, calibration) but are NOT part of the agent-facing tool schema contract. The tool schema deliberately hides them.

## Change 3: Tool Schema

### File: `distill_tool/tool_schema.json` (new)

```json
[
  {
    "name": "research_search",
    "description": "Search the indexed research corpus for specific topics, data points, or market themes. Returns ranked text chunks with source attribution and dates. Use focused, narrow queries — not full analytical questions. For complex topics, call multiple times with different angles and combine the results yourself.",
    "parameters": {
      "type": "object",
      "required": ["query"],
      "properties": {
        "query": {
          "type": "string",
          "description": "A focused search query targeting a specific concept, data point, or theme. Examples: 'CPI print January 2025', 'Fed dot plot rate expectations', 'labor market softening signals'. Do NOT pass full analytical questions."
        },
        "date_from": {
          "type": "string",
          "description": "ISO date lower bound, inclusive (e.g. '2025-01-01'). Omit to search all dates."
        },
        "date_to": {
          "type": "string",
          "description": "ISO date upper bound, inclusive (e.g. '2025-01-31'). Omit to search all dates."
        },
        "limit": {
          "type": "integer",
          "description": "Max results to return. Default 10. Use 5 for narrow queries, 15-20 for broad sweeps.",
          "default": 10
        }
      }
    }
  },
  {
    "name": "research_corpus_info",
    "description": "Returns metadata about the research corpus: total chunks, date range covered, and list of sources. Call this first to understand what data is available before searching.",
    "parameters": {
      "type": "object",
      "properties": {}
    }
  }
]
```

**Schema design rationale:**

- **Two tools, not one.** `corpus_info` is a separate tool so the search schema stays clean.
- **`keyword_weight` / `semantic_weight` / `run_id` NOT exposed.** These are tuning internals. Fewer parameters = better model decisions.
- **The description steers agent behavior.** "Do NOT pass full analytical questions" and "call multiple times with different angles" are the critical instructions shaping how the agent decomposes queries.

## Change 4: Package Integration

### File: `distill_tool/__init__.py` (edit)

```python
from distill_tool.pipeline import distill_file, distill_markdown
from distill_tool.search import HybridSearchEngine
from distill_tool.api import search, corpus_info

__all__ = ["distill_file", "distill_markdown", "HybridSearchEngine", "search", "corpus_info"]
```

### No other package changes

- No new CLI entry points (the API is for programmatic agent consumption)
- No new dependencies
- No changes to `pyproject.toml` or `setup.cfg`

## File Change Summary

| File | Action | Description |
|---|---|---|
| `distill_tool/search.py` | Edit | Add `date_from`/`date_to` params, `_chunk_ids_for_date_range()` helper |
| `distill_tool/storage.py` | Edit | Add `idx_chunks_source_date` index to `init_db()` |
| `distill_tool/api.py` | New | `search()` and `corpus_info()` functions with input validation |
| `distill_tool/tool_schema.json` | New | Tool definitions for agent tool-use |
| `distill_tool/__init__.py` | Edit | Export `search`, `corpus_info` |
| `tests/test_api.py` | New | Tests for `api.search()` and `api.corpus_info()` |
| `tests/test_search_date_filter.py` | New | Tests for date-range filtering in `HybridSearchEngine` |

## What Is NOT Changed

- `pipeline.py` — ingestion pipeline untouched
- `storage.py` — minor edit: add `source_date` index to `init_db()` only
- `chunking.py` — document splitting untouched
- `keywords.py` — keyword extraction untouched
- `embeddings.py` — embedding model untouched
- `supabase_indexer.py` — background indexer untouched
- All existing CLIs — remain for human use
- `pyproject.toml` / `setup.cfg` — no new entry points or dependencies

## Testing Strategy

**`tests/test_search_date_filter.py`:**
- Create a SQLite DB with chunks spanning multiple `source_date` values, including some with `NULL` `source_date`
- Verify `date_from` only, `date_to` only, both, and neither
- Verify chunks with `NULL` `source_date` are excluded when date filters are active
- Verify chunks with `NULL` `source_date` are included when no date filter is set
- Verify date filtering interacts correctly with `run_id` filtering (intersection)
- Verify semantic path respects date mask
- Verify a date range matching zero chunks returns an empty list (not an error)

**`tests/test_api.py`:**
- Test `search()` returns list of plain dicts with expected keys
- Test `corpus_info()` returns correct aggregates
- Test `corpus_info()` on empty database returns `total_chunks=0`, `date_range=None`, `sources=[]`
- Test `corpus_info()` when all chunks have `NULL` `source_date` returns `date_range=None`
- Test `search()` with date filters passes them through correctly
- Test `search()` raises `ValueError` on malformed date strings (e.g., "January 2025")

## Example Agent Usage Pattern

```
Agent receives: "What was the consensus on CPI in January 2025
                 and how did that relate to Fed cut expectations?"

Agent calls: research_corpus_info()
  -> learns corpus covers 2024-09 to 2025-03, has 47 sources

Agent calls: research_search(
    query="CPI consensus expectations",
    date_from="2025-01-01", date_to="2025-01-31", limit=10)

Agent calls: research_search(
    query="Fed rate cut expectations",
    date_from="2025-01-01", date_to="2025-02-15", limit=10)

Agent calls: research_search(
    query="inflation surprise market reaction",
    date_from="2025-01-01", date_to="2025-01-31", limit=5)

Agent synthesizes answer from the combined ~25 chunks,
citing source_path and source_date for attribution.
```
