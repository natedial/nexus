# Structured Fact Extraction Layer Design

**Date:** 2026-03-16
**Status:** Draft
**Scope:** Add an LLM-powered fact extraction pass that converts prose chunks into structured `(entity, metric, value, direction)` tuples stored in SQLite, with a `fact_lookup()` query API and agent tool schema.

## Problem

The agentic retrieval API (2026-03-15) gives agents a text search primitive. Agents decompose complex questions into sub-queries and synthesize prose results. This works, but for the most common query pattern — "what was CPI in January 2025?" — the agent must read through multiple prose chunks to find a single structured data point buried in narrative text.

Two retrieval modes are needed:

- **`search()`** — "what did people say about X?" → prose, narrative, qualitative context
- **`fact_lookup()`** — "what *was* X?" → structured data points, instant answers

The fact extraction layer runs as a separate post-processing pass over already-ingested chunks. It uses an LLM to extract structured facts from each chunk's text and stores them in relational tables. The agent then has two tools: `research_search` for prose retrieval and `research_fact_lookup` for structured queries.

## Design Principles

1. **Separate pass, not inline.** Fact extraction is decoupled from ingestion (`distill_file`/`distill_markdown`). This allows iterating on extraction prompts without re-ingesting documents, re-extracting with different models, and extracting from already-ingested corpora.
2. **Pluggable LLM.** The extractor accepts a `Callable[[list[dict]], list[dict]]` — no hard dependency on any provider. A built-in Anthropic adapter is provided for convenience but lives behind an optional import.
3. **Relational, not graph.** Facts and relationships are stored in SQLite tables (`facts`, `fact_links`), not a graph database. LLMs generate SQL better than Cypher, the corpus scale doesn't justify Neo4j, and the data model is already graph-shaped for future migration.
4. **Entity normalization via prompt.** The extraction prompt instructs the LLM to use canonical entity names. An optional entity config file provides domain-specific canonical mappings the LLM references during extraction.
5. **Incremental extraction.** Chunks are tracked as processed via a sentinel row in the `facts` table (entity=`"_extracted"`, confidence=0). This prevents re-processing chunks that legitimately contain no extractable facts. Re-extraction can be forced per-chunk or globally.

## Architecture

```
[LLM Agent]
    |
    |-- calls corpus_info() to discover date range & sources
    |
    |-- calls fact_lookup(entity, date_from, date_to) for structured data
    |       |
    |       v
    |   [api.py] -- SQL query against facts table
    |       |
    |       v
    |   list[dict] -- structured fact rows
    |
    |-- calls search() for prose/narrative context
    |       |
    |       v
    |   [api.py -> HybridSearchEngine] -- existing text search
    |
    |-- synthesizes answer combining structured facts + prose context

[Extraction Pipeline] (separate, offline)
    |
    |-- reads chunks from SQLite
    |-- batches chunks (N per LLM call)
    |-- sends extraction prompt to LLM callable
    |-- parses structured JSON response
    |-- stores facts + fact_links in SQLite
```

## Change 1: Database Schema

### File: `distill_tool/storage.py`

**New tables added to `init_db()`:**

```sql
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    metric TEXT,
    value TEXT,
    direction TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_date TEXT,
    extraction_model TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
)
```

```sql
CREATE TABLE IF NOT EXISTS fact_links (
    link_id TEXT PRIMARY KEY,
    source_fact_id TEXT NOT NULL,
    target_fact_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 1.0,
    FOREIGN KEY(source_fact_id) REFERENCES facts(fact_id),
    FOREIGN KEY(target_fact_id) REFERENCES facts(fact_id)
)
```

**Indexes:**

```sql
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity);
CREATE INDEX IF NOT EXISTS idx_facts_source_date ON facts(source_date);
CREATE INDEX IF NOT EXISTS idx_facts_chunk_id ON facts(chunk_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_source ON fact_links(source_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_target ON fact_links(target_fact_id);
```

**Column semantics:**

| Column | Type | Description |
|---|---|---|
| `fact_id` | TEXT | SHA256 hash of `chunk_id|entity|metric|value|direction` for dedup (NULLs as empty string) |
| `chunk_id` | TEXT | FK to `chunks.chunk_id` — provenance back to source text |
| `entity` | TEXT | Canonical entity name: `"CPI"`, `"fed_funds_rate"`, `"unemployment"`, `"sp500"` |
| `metric` | TEXT | What's being measured: `"actual"`, `"consensus"`, `"forecast"`, `"estimate"`, `"probability"`, `"trend"`, `"change"`, `"level"`, `"spread"`, `"ratio"` |
| `value` | TEXT | Specific value if stated: `"3.1%"`, `"25bps"`, `"$4.2T"`. Null if directional-only |
| `direction` | TEXT | Signal: `"above"`, `"below"`, `"rising"`, `"declining"`, `"hawkish"`, `"dovish"`, `"flat"` |
| `confidence` | REAL | LLM's extraction confidence, 0.0–1.0 |
| `source_date` | TEXT | Inherited from `chunks.source_date` — not re-extracted |
| `extraction_model` | TEXT | Model identifier used for extraction (e.g., `"claude-haiku-4-5-20251001"`) |

**`fact_links` relationship types:**

| Relationship | Meaning | Example |
|---|---|---|
| `causes` | Source fact causes target | CPI surprise → reduced Fed cut expectations |
| `supports` | Source fact supports target | Strong jobs → hawkish Fed stance |
| `contradicts` | Source fact contradicts target | Low inflation vs. high wage growth |
| `precedes` | Source fact temporally precedes target | Rate hike → market selloff |

**`fact_id` generation:** Hash of `chunk_id|entity|metric|value|direction` ensures the same fact extracted from the same chunk is idempotent. NULL fields are represented as empty strings in the hash input (e.g., a fact with entity="CPI", metric=None, value=None, direction="rising" hashes as `SHA256("chunk123|CPI|||rising")`). The `direction` field is included in the hash because two facts from the same chunk with the same entity/metric/value but different directions (e.g., "rising" vs. "declining") are semantically distinct and must not collide. Different chunks containing the same data point produce different `fact_id`s — this is intentional, as each extraction carries its own provenance.

**`link_id` generation:** Hash of `source_fact_id|target_fact_id|relationship` — deterministic and idempotent, same pattern as `fact_id`.

**`strength` column:** Always 1.0 in this iteration. The extraction prompt does not ask the LLM to output strength values. The column exists for future use (e.g., confidence-weighted relationship scoring) but is not actively populated.

**`source_date` inheritance:** The fact's `source_date` is copied from its parent chunk at extraction time. This avoids asking the LLM to parse dates (unreliable) and ensures temporal consistency with existing date-range filtering.

## Change 2: Extraction Module

### File: `distill_tool/facts.py` (new)

**LLM interface:**

```python
from typing import Callable, TypeAlias

# Input: list of {"chunk_id": str, "text": str, "source_date": str | None}
# Output: list of {"chunk_id": str, "facts": [...], "links": [...]}
ExtractorCallable: TypeAlias = Callable[[list[dict]], list[dict]]
```

The callable receives a list of chunks and returns structured extractions. When `extractor` is provided directly to `extract_facts()`, ALL selected chunks are passed in a single call — the extractor is responsible for its own internal batching/chunking. This gives full control to custom implementations.

**However**, to make common usage simple, the module provides a prompt builder and a response parser so that callers only need to provide a raw LLM call function. When `llm` is provided instead, `extract_facts()` wraps it with `make_extractor()` which handles batching internally (splitting chunks into groups of `batch_size` and making one LLM call per group):

```python
# Simple interface: user provides just the LLM call
LLMCallable: TypeAlias = Callable[[str], str]  # prompt -> response text

def make_extractor(
    llm: LLMCallable,
    *,
    batch_size: int = 5,
    entity_config: dict | None = None,
) -> ExtractorCallable:
    """Wrap a raw LLM callable into a batched fact extractor.

    The returned callable handles prompt construction, batching,
    and JSON response parsing.
    """
```

**Built-in Anthropic adapter:**

```python
def anthropic_llm(
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 4096,
) -> LLMCallable:
    """Create an LLM callable using the Anthropic SDK.

    Requires the `anthropic` package and ANTHROPIC_API_KEY env var.
    """
    import anthropic
    client = anthropic.Anthropic()

    def call(prompt: str) -> str:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    return call
```

`anthropic` is NOT added to `pyproject.toml` dependencies. It's an optional import — the user installs it themselves. This keeps the core package dependency-free of LLM SDKs.

**Main extraction function:**

```python
def extract_facts(
    db_path: str,
    *,
    extractor: ExtractorCallable | None = None,
    llm: LLMCallable | None = None,
    batch_size: int = 5,
    entity_config_path: str | None = None,
    chunk_ids: list[str] | None = None,
    force: bool = False,
) -> FactExtractionResult:
    """Extract structured facts from corpus chunks.

    Either `extractor` or `llm` must be provided. If `llm` is given,
    it is wrapped with `make_extractor()`.

    Args:
        db_path: Path to the SQLite database.
        extractor: A batched extraction callable.
        llm: A raw LLM callable (prompt -> response). Wrapped automatically.
        batch_size: Chunks per LLM call (only used with `llm`).
        entity_config_path: Optional JSON file with canonical entity mappings.
        chunk_ids: Extract from specific chunks only. None = all chunks.
        force: Re-extract even if facts already exist for a chunk.

    Returns:
        FactExtractionResult with counts of facts/links extracted.
    """
```

**Extraction logic flow:**

1. Load entity config (if provided)
2. Query chunks to extract: all chunks (or specific `chunk_ids`), minus those already having a sentinel row in `facts` (entity=`"_extracted"`) unless `force=True`
3. Batch chunks into groups of `batch_size`
4. For each batch, call the extractor
5. Parse response, generate `fact_id` and `link_id` hashes, store facts and fact_links
6. For each processed chunk (including those with zero extracted facts), insert a sentinel row: `(fact_id=hash(chunk_id|"_extracted"), chunk_id, entity="_extracted", confidence=0)`. This marks the chunk as processed so it won't be re-processed on subsequent runs.
7. Return summary stats

**Sentinel rows** are excluded from all query functions (`query_facts`, `fact_lookup`) via `WHERE entity != '_extracted'`. They are only used for incremental tracking.

**Entity config file format (optional):**

```json
{
  "canonical_entities": {
    "CPI": ["consumer price index", "inflation rate", "CPI print"],
    "fed_funds_rate": ["federal funds rate", "Fed rate", "policy rate"],
    "unemployment": ["jobless rate", "unemployment rate"],
    "NFP": ["nonfarm payrolls", "jobs report", "employment change"],
    "sp500": ["S&P 500", "SPX", "equities"],
    "treasury_10y": ["10-year yield", "10Y", "long bond"]
  }
}
```

This file is included in the extraction prompt so the LLM normalizes to canonical names. If not provided, the LLM uses its own judgment (still works, just less consistent).

**Extraction prompt template:**

The prompt is the most critical design element. It must produce structured, parseable JSON with consistent entity names.

```
Extract structured facts from the following financial research text chunks.

For each distinct factual claim, extract:
- entity: The canonical subject (see entity list below if provided)
- metric: What is measured — one of: actual, consensus, forecast, estimate,
  probability, trend, change, level, spread, ratio
- value: The specific value if stated (e.g., "3.1%", "25bps", "$4.2T").
  Null if only directional.
- direction: Directional signal if present — one of: above, below, rising,
  declining, hawkish, dovish, flat, stronger, weaker, tightening, easing.
  Null if purely numeric with no directional context.
- confidence: Your confidence in this extraction, 0.0 to 1.0.

If a chunk contains no extractable factual claims, return an empty facts
array for that chunk. Every chunk in the input MUST appear in the output.

For causal or logical relationships between facts within the SAME chunk:
- source_index: Index of the cause/antecedent fact in the facts array
- target_index: Index of the effect/consequent fact in the facts array
- relationship: One of: causes, supports, contradicts, precedes

{entity_config_section}

Return valid JSON only, no other text:
{{
  "chunks": [
    {{
      "chunk_id": "<chunk_id>",
      "facts": [
        {{"entity": "...", "metric": "...", "value": "...",
          "direction": "...", "confidence": 0.95}}
      ],
      "links": [
        {{"source_index": 0, "target_index": 1, "relationship": "causes"}}
      ]
    }}
  ]
}}

--- CHUNKS ---

{chunk_texts}
```

**Response parsing:**

The parser handles common LLM response issues:
- Strips markdown code fences if present
- Validates JSON structure
- Validates fact fields against allowed enums (metric, direction, relationship)
- Drops facts with missing required fields (`entity`) rather than failing the batch
- Generates deterministic `fact_id` and `link_id` hashes
- Logs warnings for dropped/invalid extractions

**FactExtractionResult dataclass:**

```python
@dataclass(frozen=True)
class FactExtractionResult:
    chunks_processed: int
    facts_extracted: int
    links_extracted: int
    chunks_skipped: int     # already had facts (when force=False)
    chunks_failed: int      # LLM call or parse failure
    errors: list[str]       # error messages for failed chunks
```

**Fact storage helper:**

```python
def store_facts(
    db_path: str,
    facts: list[dict],
    links: list[dict],
) -> None:
    """Store extracted facts and links in the database.

    Uses INSERT OR REPLACE for idempotency (fact_id is deterministic).
    """
```

**Fact query helpers:**

```python
def query_facts(
    db_path: str,
    *,
    entity: str | None = None,
    metric: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> list[dict]:
    """Query the facts table with optional filters.

    Returns list of dicts with all fact columns plus the source chunk's text.
    """
```

```python
def query_fact_connections(
    db_path: str,
    *,
    entity: str | None = None,
    fact_id: str | None = None,
    relationship: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Find facts connected to a given entity or fact.

    Returns list of dicts describing the link and both connected facts.
    """
```

## Change 3: API Additions

### File: `distill_tool/api.py`

Add two new functions to the existing API module:

```python
def fact_lookup(
    *,
    db_path: str,
    entity: str | None = None,
    metric: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_confidence: float = 0.5,
    limit: int = 20,
) -> list[dict]:
    """Look up structured facts from the extracted fact table.

    Returns list of dicts with keys:
        fact_id, chunk_id, entity, metric, value, direction,
        confidence, source_date, source_text (truncated to 200 chars)
    """
```

```python
def fact_connections(
    *,
    db_path: str,
    entity: str | None = None,
    fact_id: str | None = None,
    relationship: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Find facts that are causally or logically connected.

    Returns list of dicts with keys:
        link_id, relationship, strength,
        source_fact (dict), target_fact (dict)
    """
```

**Design decisions:**

- **`min_confidence` defaults to 0.5** in the API. Low-confidence facts are still stored (for analysis/debugging) but hidden from the agent by default. The `min_confidence` parameter is available to programmatic callers but is NOT exposed in the agent tool schema — the 0.5 default is the right threshold for agent use.
- **`source_text` is truncated to 200 chars.** The agent gets a preview of the chunk text for context. If it needs the full text, it can use `research_search` with the `chunk_id` or call `search()` for the same topic.
- **`entity` parameter does case-insensitive matching.** The query normalizes both the input and the stored entity with `LOWER()` for resilience against casing inconsistencies.
- **Date validation reuses `_validate_date()`** from the existing API module.

### File: `distill_tool/api.py` — update `corpus_info()`

Add fact statistics to the existing `corpus_info()` return:

```python
def corpus_info(db_path: str) -> dict:
    # ... existing fields ...
    # Add:
    total_facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    fact_entities = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT entity FROM facts ORDER BY entity"
        ).fetchall()
    ]
    return {
        # ... existing ...
        "total_facts": total_facts,
        "fact_entities": fact_entities,
    }
```

This tells the agent whether facts are available and what entities exist, so it knows when to use `fact_lookup` vs `search`.

**Graceful degradation:** If the `facts` table doesn't exist yet (older database), `corpus_info()` returns `total_facts: 0` and `fact_entities: []`. Same for `fact_lookup()` — returns `[]`. The detection mechanism: wrap fact-table queries in `try/except sqlite3.OperationalError` and return the empty defaults on failure. This is simpler and more robust than checking `sqlite_master` — it handles both missing tables and schema mismatches.

## Change 4: Tool Schema

### File: `distill_tool/tool_schema.json`

Add one new tool definition:

```json
{
  "name": "research_fact_lookup",
  "description": "Look up structured data points extracted from the research corpus. Returns specific values, metrics, and directional signals for financial entities. Use this for precise questions like 'what was CPI?' or 'what were Fed rate expectations?'. Use research_search instead for narrative context, qualitative analysis, or themes.",
  "parameters": {
    "type": "object",
    "properties": {
      "entity": {
        "type": "string",
        "description": "The entity to look up. Examples: 'CPI', 'fed_funds_rate', 'unemployment', 'NFP', 'sp500'. Use research_corpus_info to see available entities."
      },
      "metric": {
        "type": "string",
        "description": "Filter by metric type: 'actual', 'consensus', 'forecast', 'probability', 'trend', 'change'. Omit to see all metrics."
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
        "description": "Max results. Default 20.",
        "default": 20
      }
    }
  }
}
```

**Update `research_corpus_info` description** to mention fact availability:

```json
"description": "Returns metadata about the research corpus: total chunks, date range covered, list of sources, and available structured fact entities. Call this first to understand what data is available before searching or looking up facts."
```

**`research_fact_connections` is NOT exposed as a tool.** The connections API exists for programmatic use, but the agent doesn't need it as a separate tool — when it calls `fact_lookup`, the returned facts already carry enough context for the agent to reason about relationships. Adding a third retrieval tool increases decision complexity for the agent without proportional benefit. If usage patterns show the agent struggling to find causal chains, this tool can be added later.

## Change 5: CLI

### File: `distill_tool/fact_cli.py` (new)

A simple CLI for running fact extraction from the command line:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Extract structured facts from corpus")
    parser.add_argument("db_path", help="Path to SQLite database")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001",
                        help="Anthropic model for extraction")
    parser.add_argument("--batch-size", type=int, default=5,
                        help="Chunks per LLM call")
    parser.add_argument("--entity-config", help="Path to entity config JSON")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract even if facts exist")
    parser.add_argument("--chunk-ids", nargs="*",
                        help="Extract specific chunks only")
```

### File: `pyproject.toml`

Add entry point:

```toml
[project.scripts]
# ... existing ...
distill-extract-facts = "distill_tool.fact_cli:main"
```

**No new required dependencies.** The `anthropic` package is an optional dependency. The CLI imports it at runtime and gives a clear error message if it's not installed.

## Change 6: Package Integration

### File: `distill_tool/__init__.py`

Add new exports:

```python
from distill_tool.api import search, corpus_info, fact_lookup, fact_connections

__all__ = [
    "distill_file", "distill_markdown", "HybridSearchEngine",
    "search", "corpus_info", "fact_lookup", "fact_connections",
]
```

## File Change Summary

| File | Action | Description |
|---|---|---|
| `distill_tool/storage.py` | Edit | Add `facts`, `fact_links` tables and indexes to `init_db()` |
| `distill_tool/facts.py` | New | Extraction logic, prompt builder, response parser, fact storage/query |
| `distill_tool/api.py` | Edit | Add `fact_lookup()`, `fact_connections()`, update `corpus_info()` |
| `distill_tool/tool_schema.json` | Edit | Add `research_fact_lookup` tool definition |
| `distill_tool/fact_cli.py` | New | CLI entry point for running extraction |
| `distill_tool/__init__.py` | Edit | Export `fact_lookup`, `fact_connections` |
| `pyproject.toml` | Edit | Add `distill-extract-facts` entry point |
| `tests/test_facts.py` | New | Tests for extraction, storage, and query functions |
| `tests/test_fact_api.py` | New | Tests for `fact_lookup()`, `fact_connections()`, updated `corpus_info()` |

## What Is NOT Changed

- `pipeline.py` — ingestion pipeline untouched
- `search.py` — hybrid search engine untouched
- `chunking.py`, `keywords.py`, `embeddings.py` — untouched
- `supabase_indexer.py` — untouched
- Existing tests — untouched
- Existing tool schema for `research_search` — untouched
- `research_corpus_info` tool description updated to mention fact availability (see Change 4)

## Testing Strategy

### `tests/test_facts.py`

**Extraction prompt & parsing:**
- Test prompt construction with and without entity config
- Test JSON response parsing with valid response
- Test response parsing with markdown code fences (common LLM behavior)
- Test response parsing drops facts missing required `entity` field
- Test response parsing validates enum fields (`metric`, `direction`, `relationship`)
- Test response parsing handles malformed JSON gracefully (returns error, doesn't crash)

**Fact storage:**
- Test `store_facts()` inserts facts correctly
- Test `store_facts()` is idempotent (same fact_id = replace, not duplicate)
- Test `store_facts()` inserts fact_links with correct FK references
- Test `fact_id` generation is deterministic: same input = same hash

**Fact queries:**
- Test `query_facts()` with no filters returns all facts
- Test `query_facts()` filtering by entity (case-insensitive)
- Test `query_facts()` filtering by metric
- Test `query_facts()` filtering by date range
- Test `query_facts()` filtering by min_confidence
- Test `query_facts()` with combined filters
- Test `query_facts()` on empty table returns `[]`
- Test `query_fact_connections()` returns connected facts
- Test `query_fact_connections()` filtering by relationship type

**Integration (with mock LLM):**
- Test `extract_facts()` end-to-end with a mock LLM callable
- Test `extract_facts()` skips chunks that already have sentinel rows
- Test `extract_facts()` inserts sentinel row for chunks with zero extracted facts
- Test `extract_facts()` with `force=True` re-extracts (ignores sentinel rows)
- Test `extract_facts()` with `chunk_ids` filter
- Test `query_facts()` excludes sentinel rows (entity="_extracted")

### `tests/test_fact_api.py`

- Test `fact_lookup()` returns list of dicts with expected keys
- Test `fact_lookup()` date validation raises ValueError on bad format
- Test `fact_lookup()` case-insensitive entity matching
- Test `fact_connections()` returns linked facts
- Test updated `corpus_info()` includes `total_facts` and `fact_entities`
- Test `corpus_info()` graceful degradation when `facts` table doesn't exist
- Test `fact_lookup()` returns `[]` when `facts` table doesn't exist

All tests use mock LLM callables (return pre-built JSON strings). No actual LLM API calls in tests.

## Example Agent Usage Pattern

```
Agent receives: "What was the consensus on CPI in January 2025
                 and how did that relate to Fed cut expectations?"

Agent calls: research_corpus_info()
  -> learns corpus has 342 facts, entities include CPI, fed_funds_rate, ...

Agent calls: research_fact_lookup(
    entity="CPI", date_from="2025-01-01", date_to="2025-01-31")
  -> gets: [{entity: "CPI", metric: "actual", value: "3.1%",
             direction: "above", confidence: 0.95, source_date: "2025-01-15"},
            {entity: "CPI", metric: "consensus", value: "2.9%",
             confidence: 0.92, source_date: "2025-01-10"}]

Agent calls: research_fact_lookup(
    entity="fed_funds_rate", metric="probability",
    date_from="2025-01-01", date_to="2025-02-15")
  -> gets: [{entity: "fed_funds_rate", metric: "probability",
             value: "62%", direction: "declining",
             source_date: "2025-01-20"}]

Agent calls: research_search(
    query="CPI surprise impact on Fed rate cut expectations",
    date_from="2025-01-15", date_to="2025-02-01", limit=5)
  -> gets narrative context connecting the two data points

Agent synthesizes: "CPI came in at 3.1% YoY in January, above the
2.9% consensus. Following the print, market-implied probability of
a March cut dropped to 62%, down from ..."
```

The fact lookup gives the agent precise numbers instantly. The text search fills in the narrative reasoning. Together they produce a well-sourced analytical answer.
