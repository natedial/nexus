# Report Storage Target State Plan - 2026-05-19

## Summary

This plan turns the findings in `docs/report_storage_assessment_2026-05-19.md` into a minimal implementation path.

The goal is to improve downstream querying, auditability, and analysis quality without replacing the current parser, analyst, and dispatcher boundaries.

Core approach:

- Keep `parsed_research.parsed_data` unchanged for compatibility.
- Keep normalized themes/excerpts and current analyst theme-first processing for now.
- Add stable parser-owned source spans and retrieval chunks.
- Attach span/chunk provenance to existing excerpts and normalized trades.
- Propagate citation metadata through analyst evidence and dispatcher snapshots.
- Defer parser-owned claims/entities/relations until ownership is deliberately clarified.

## Target Ownership

### `research_parser`

Owns ingestion and durable source grounding:

- document identity
- parser artifacts
- cleaned text
- document-local extractions
- source spans
- retrieval chunks
- normalized themes/excerpts
- normalized document-local trades

### `research_analyst`

Owns document-level and graph/world-model analysis:

- analysis chunks
- evidence units
- assertions
- forecast extraction
- world nodes/edges
- debate and agent outputs
- quality gates
- dispatcher batch export

### `research_dispatcher`

Owns synthesis and reporting:

- cross-document through-lines
- PM-facing narrative synthesis
- report formatting
- PDF/email delivery
- dispatch run history and snapshots

The weak contract to fix is evidence addressability across handoffs, not repo ownership.

## Implementation Plan

### 1. Add Additive Schema Support

Create a new migration after `004_research_memory_substrate.sql`.

Add nullable provenance fields to `research_theme_excerpts`:

- `span_key TEXT NULL`
- `chunk_key TEXT NULL`
- `page_ref TEXT NULL`
- `source_ref JSONB NOT NULL DEFAULT '{}'`

Add indexes:

- `idx_research_theme_excerpts_span_key`
- `idx_research_theme_excerpts_chunk_key`

Add a simple parser-owned `research_trades` table:

- `id BIGSERIAL PRIMARY KEY`
- `research_id BIGINT NOT NULL REFERENCES parsed_research(id) ON DELETE CASCADE`
- `trade_order INTEGER NOT NULL`
- `text TEXT NOT NULL`
- `exposure TEXT NULL`
- `timeframe TEXT NULL`
- `conviction TEXT NULL`
- `rationale TEXT NULL`
- `trigger_levels TEXT NULL`
- `span_key TEXT NULL REFERENCES research_spans(span_key) ON DELETE SET NULL`
- `chunk_key TEXT NULL REFERENCES research_retrieval_chunks(chunk_key) ON DELETE SET NULL`
- `page_ref TEXT NULL`
- `source_ref JSONB NOT NULL DEFAULT '{}'`
- `extraction_version TEXT NOT NULL DEFAULT 'parser-trades-v1'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `UNIQUE(research_id, extraction_version, trade_order)`

Add indexes:

- `idx_research_trades_research_id`
- `idx_research_trades_span_key`
- `idx_research_trades_chunk_key`
- `idx_research_trades_conviction`
- `idx_research_trades_timeframe`

Add full-text search support for retrieval chunks:

- Add a generated or maintained `tsvector` column for `research_retrieval_chunks.text`.
- Add a GIN index on that vector.

Defer `pgvector` until embedding generation is actually implemented.

### 2. Extend Parser Storage With Artifact Context

Extend `SupabaseClient.insert_research(...)` in a backward-compatible way:

```python
def insert_research(
    self,
    result: ExtractionResult,
    document_name: str,
    *,
    artifact_context: ResearchArtifactContext | None = None,
) -> dict:
    ...
```

`artifact_context` should include:

- `parser_version`
- `parse_backend`
- `parse_confidence_score`
- `parse_confidence_status`
- `raw_markdown_path`
- `clean_text_path`
- `figure_manifest`
- `artifact_manifest`

Default behavior must continue to work when `artifact_context` is omitted.

Update `src/pipeline.py` to pass this context after parsing and artifact creation.

### 3. Wire Source Spans And Retrieval Chunks Into Live Writes

After the `parsed_research` row is created or updated:

1. Compute `document_hash` from `result.full_text`, as today.
2. Build spans with `build_paragraph_spans(result.full_text, document_hash=document_hash)`.
3. Build retrieval chunks with `build_retrieval_chunks(spans, document_hash=document_hash)`.
4. Replace rows for the current `research_id` and active span/chunker versions:
   - `research_document_artifacts`
   - `research_spans`
   - `research_retrieval_chunks`

Replacement should be idempotent:

- Delete rows for the target `research_id` and active version.
- Insert the rebuilt rows.
- Do not delete unrelated versions.

Storage should remain best-effort for memory substrate rows:

- If `parsed_research` and normalized themes succeed but memory substrate write fails, log the failure and return the persisted research row.
- Add enough logging to identify the failing table and `research_id`.

### 4. Attach Provenance To Theme Excerpts

Update `_replace_normalized_themes(...)` so each excerpt row can include provenance.

Matching rule:

1. Try exact substring match of `excerpt.text` inside a paragraph span.
2. Fall back to normalized whitespace and case-insensitive containment.
3. Select the first best span match by `span_order`.
4. Find the first retrieval chunk containing that `span_key`.
5. Populate:
   - `span_key`
   - `chunk_key`
   - `page_ref`
   - `source_ref`

If no match is found:

- Insert the excerpt anyway.
- Set `source_ref.match_status = "unmatched"`.
- Do not fail the document write.

Recommended `source_ref` shape:

```json
{
  "match_status": "matched",
  "match_method": "exact_substring",
  "span_order": 12,
  "chunk_order": 3,
  "span_text_hash": "..."
}
```

### 5. Normalize Parser Trades

Add `_replace_normalized_trades(...)` to `SupabaseClient`.

Behavior:

- Delete existing `research_trades` rows for the target `research_id` and extraction version.
- Insert one row per `result.trades` item.
- Match trade `text` first, then `rationale`, against spans using the same matching helper used for excerpts.
- Store unmatched trades with `source_ref.match_status = "unmatched"`.

Keep `parsed_data.trades` unchanged.

### 6. Add Memory Backfill Script

Create `scripts/backfill_research_memory.py`.

It should:

- Read existing `parsed_research` rows.
- Pull `full_text`, themes, and trades from `parsed_data`.
- Compute or repair `document_hash`.
- Rebuild spans and retrieval chunks.
- Enrich `research_theme_excerpts` where possible.
- Populate `research_trades`.
- Support `--dry-run`, `--batch-size`, `--resume-from`, and `--limit`.
- Be idempotent per `research_id`.

Use the style of `scripts/backfill_theme_normalization.py`, but keep this script focused on the memory/provenance layer.

### 7. Propagate Provenance Through `research_analyst`

Update analyst hydration models:

- Add optional `span_key`, `chunk_key`, `page_ref`, and `source_ref` to `ParsedExcerpt`.
- Update `ParsedDbClient.fetch_excerpts()` to select these fields.
- Treat missing fields as legacy-safe defaults.

Keep `Chunker` theme-first for this pass.

Update `EvidenceBuilder`:

- For excerpt evidence, include parser provenance in `source_ref`.
- Include:
  - `parser_excerpt_id`
  - `parser_theme_id`
  - `span_key`
  - `chunk_key`
  - `page_ref`
  - original parser `source_ref`

Do not introduce source-span chunking in this pass. Once provenance is flowing, that can be a separate quality upgrade.

### 8. Preserve Citation Metadata In Dispatcher Flow

Update analyst dispatch export:

- Include compact citation/source metadata wherever available for:
  - themes
  - assertions
  - trades
  - trading opportunities
  - short-horizon insights
  - talking points

Update dispatcher models:

- Add optional `source_refs` or `citation_refs` fields to the relevant typed models.
- Keep parsing legacy batches without those fields.

Update `ThroughlineInputBuilder`:

- Carry citation refs into synthesis input when present.
- Omit them cleanly for legacy records.

Update dispatcher snapshots:

- Preserve the citation map used for each synthesis run.
- Do not make dispatcher query parser span/chunk tables directly.

## Testing Plan

### Parser Tests

Add or update tests to verify:

- Source spans and retrieval chunks are written for a stored document.
- Re-running storage for the same document replaces spans/chunks/themes/trades idempotently.
- Theme excerpts receive `span_key` and `chunk_key` when exact matches exist.
- Unmatched excerpts remain stored with `source_ref.match_status = "unmatched"`.
- Normalized trades are stored and evidence-linked where possible.
- Existing `parsed_data` compatibility remains unchanged.

### Backfill Tests

Add tests to verify:

- `--dry-run` does not mutate fake tables.
- Existing legacy rows can produce spans/chunks from `parsed_data.full_text`.
- Existing theme excerpts can be enriched with provenance.
- Trades can be populated from `parsed_data.trades`.
- Reruns are idempotent.

### Analyst Tests

Add or update tests to verify:

- `ParsedDbClient` hydrates legacy excerpts without provenance.
- `ParsedDbClient` hydrates enriched excerpts with provenance.
- `EvidenceBuilder` includes parser span/chunk keys in evidence `source_ref`.
- Agent input still uses existing local `chunk-{order}` keys while carrying parser source refs.

### Dispatcher Tests

Add or update tests to verify:

- Analyst batch models accept citation metadata.
- Legacy batches without citation metadata still parse.
- `ThroughlineInputBuilder` includes citation refs when present.
- Dispatch snapshots retain citation metadata.

### End-To-End Smoke Scenario

Run one fixture document through:

1. parser storage
2. analyst analysis
3. analyst dispatch batch export
4. dispatcher synthesis

Confirm:

- `parsed_research` is populated.
- `research_spans` is populated.
- `research_retrieval_chunks` is populated.
- `research_theme_excerpts` includes provenance where matched.
- `research_trades` is populated.
- analyst evidence includes parser source refs.
- dispatcher can synthesize with no legacy behavior regression.

## Rollout Order

1. Apply schema migration.
2. Add parser memory write helpers and unit tests.
3. Wire helpers into `insert_research(...)` with best-effort failure handling.
4. Add normalized trade writes.
5. Add memory backfill script.
6. Update `research_analyst` hydration and evidence propagation.
7. Update analyst dispatch export and dispatcher citation preservation.
8. Run backfill in dry-run mode.
9. Run backfill on a small limit.
10. Run full backfill.
11. Enable downstream use of citation refs in synthesis prompts.

## Explicit Non-Goals For This Pass

- Do not rewrite parser extraction prompts.
- Do not replace analyst theme-first chunking with source-span chunking yet.
- Do not activate parser-owned claims/entities/relations as a competing semantic authority.
- Do not introduce vector embeddings until there is an embedding writer and retrieval consumer.
- Do not make dispatcher a retrieval or citation lookup service.

## Defaults And Assumptions

- Active span version: `span-v1`.
- Active chunker version: `retrieval-chunker-v1`.
- Active trade extraction version: `parser-trades-v1`.
- Full-text search is the first retrieval index upgrade.
- Unmatched provenance is acceptable and should not block ingestion.
- Backward compatibility with existing parser, analyst, and dispatcher payloads is mandatory.
