# Report Storage Assessment - 2026-05-19

## Question

Should the current process of relying on parsed markdown plus parsed themes, trades, and macro data remain the core downstream querying and analysis substrate, or should report storage be reconsidered?

## Current Read

The current approach is solid as a first-pass ingestion and synthesis feed, but it is not strong enough as the long-term querying and analysis substrate.

Parsed markdown is useful as a source artifact. Parsed themes, trades, and macro data are useful as derived summaries. The gap is a stable, source-grounded evidence layer between raw text and model-produced interpretations.

## Evidence From The Codebase

- The live parser stores `parsed_data` JSONB with metadata, themes, trades, full text, and extraction stats in `src/storage/supabase.py`.
- The live parser dual-writes normalized theme rows and theme excerpts, but does not currently normalize trades or populate theme links.
- The pipeline still runs extraction from cleaned markdown text.
- `migrations/004_research_memory_substrate.sql` already defines a better additive substrate: document artifacts, spans, retrieval chunks, evidence units, entities, claims, relations, and memory events.
- `src/research_memory/spans.py` already contains deterministic span and retrieval chunk builders, but they do not appear wired into the live parser write path yet.
- `research_dispatcher` still has legacy paths built around `parsed_research.parsed_data`, with known mixed-mode migration concerns around normalized themes.
- `research_analyst` runs after the parser and provides a real analysis layer: chunking, evidence units, assertions, graph/world-model updates, quality gates, agent/debate outputs, and dispatch batch exports.

## Main Concern

Themes, trades, and macro data are lossy model interpretations. They are valuable, but weak as the primary query substrate because downstream systems cannot reliably answer:

- What exact paragraph, page, table, or figure supports this conclusion?
- Which claims were missed because the theme extractor did not label them correctly?
- Which documents agree or contradict at the evidence level?
- What changed across parser versions or extraction versions?
- Can we retrieve all evidence about a mechanism independent of the derived theme label?

## Recommended Storage Model

Keep the current outputs, but demote them to derived layers over a source-grounded store.

1. Source artifact layer
   - Raw PDF identity, parser backend/version, parse confidence, raw markdown path, clean text path, figure/table manifests.

2. Span layer
   - Stable paragraph/table/figure spans with `span_key`, page, section path, offsets, text hash, and text.

3. Retrieval layer
   - Span-backed chunks for hybrid lexical/vector retrieval. Chunks should always link back to exact spans.

4. Extraction layer
   - Themes, trades, macro facts, forecasts, and claims as typed derived records. Every derived record should carry evidence span keys, not just loose excerpt text.

5. Analysis layer
   - Cross-document themes, contradictions, market regimes, entity relations, and world-model objects should be downstream enrichment rather than parser-local output.

## Working Recommendation

Do not rewrite the parser around a new model immediately. Instead, add the evidence substrate behind the current flow:

1. Keep writing `parsed_research.parsed_data` for compatibility.
2. Keep normalized themes/excerpts for current dispatcher migration work.
3. After `insert_research()` succeeds, build and store spans and retrieval chunks from `ExtractionResult.full_text`.
4. Begin attaching future theme/trade/macro/claim records to span keys.
5. Move downstream querying toward span-backed retrieval and evidence-grounded derived objects.

The highest-leverage next step is wiring the existing `research_memory` span/chunk substrate into the parser write path and making downstream consumers cite evidence by span key.

## Research Analyst Addendum

Reviewing `../research_analyst` changes the assessment in an important way:

- The overall architecture is more solid than a parser-only review suggests.
- The analysis layer already owns the higher-order work that should not live in the parser: assertions, world nodes/edges, graph provenance, debate/agent analysis, forecast candidates, quality review, and dispatch batch export.
- This means the parser does not need to become the full analysis brain. Its job should stay focused on durable source capture, normalized document-local extractions, and evidence addressability.

However, `research_analyst` does not remove the need for a better source-grounded parser substrate.

The current analyst pipeline hydrates from parser-owned `parsed_research`, `research_themes`, and `research_theme_excerpts`, then creates one analysis chunk per normalized theme. Evidence units are built from theme labels, theme context, and excerpt text. Assertions and world-model updates therefore inherit the parser theme layer as their starting boundary.

That is a reasonable bootstrap, but it means much of the "true analysis" is still constrained by upstream theme extraction quality:

- If the parser misses a concept, the analyst chunker may never see it as a first-class unit.
- If a theme merges unrelated material, analyst assertions inherit that mixed boundary.
- Evidence units cite parser excerpts/order, but not stable source spans, pages, paragraph offsets, figure/table coordinates, or parser-versioned span keys.
- Agent payloads include a truncated `full_text_excerpt`, and raw forecast extraction mines `parsed_data.full_text`, but the main chunk/evidence/assertion path is still theme-first.

The revised conclusion is therefore narrower:

Do not move cross-document reasoning or world-model enrichment into `research_parser`; `research_analyst` is the right owner for that. But do strengthen `research_parser` as the source-grounding substrate that `research_analyst` can hydrate from.

## Revised Recommendation

The next architecture step should be an interface upgrade between parser and analyst, not a replacement of either repo:

1. Keep parser outputs compatible: `parsed_research.parsed_data`, normalized themes, and theme excerpts.
2. Add parser-owned source spans and retrieval chunks after successful storage.
3. Add stable span references to parser excerpts and, later, trades/macro facts.
4. Teach `research_analyst` to hydrate spans/chunks and optionally build analysis chunks from source spans, not only from parser themes.
5. Keep assertions, graph/world-model state, debate, lifecycle, and dispatch exports in `research_analyst`.
6. Treat parser themes as seeds/priors for analyst processing, not as the full observable universe.

## Research Dispatcher Addendum

Reviewing `../research_dispatcher` reinforces the revised architecture.

`research_dispatcher` is the final synthesis and reporting layer. It can operate in two modes:

- parser mode: query `parsed_research` rows directly
- analyst mode: load a dispatcher-ready batch exported by `research_analyst`

Its through-line input builder converts both modes into prompt-ready payloads. In parser mode it uses themes and trades from `parsed_data`. In analyst mode it includes richer fields from `research_analyst`: themes, trades, trading opportunities, short-horizon insights, talking points, assertions, forecasts, world nodes, and world edges.

This is the right ownership boundary:

- parser captures and normalizes source material
- analyst performs document-level and graph/world-model analysis
- dispatcher performs cross-document editorial synthesis and report generation

The dispatcher does not eliminate the source-grounding gap. It makes the need more visible:

- Stage 1 through-line synthesis is still grounded in compacted themes/trades plus optional analyst assertions/forecasts/world edges.
- Cross-document evidence clustering groups theme labels, assertion summaries, forecast keys, and world edges, but it does not carry stable source span keys.
- Stage 1C PM analysis rebuilds evidence around supporting theme labels and excerpts, not source-native paragraph/table/figure spans.
- Final report through-lines are therefore auditable to derived items, but not yet cleanly auditable back to exact source spans across parser versions.

The dispatcher should not become a retrieval store or source-citation system. Its job is narrative synthesis. But it would benefit from receiving evidence-addressed inputs from analyst/parser.

## Final Architecture Read

The three-repo architecture is directionally right:

1. `research_parser`
   - Owns ingestion, parse artifacts, document identity, cleaned text, document-local extractions, source spans, and retrieval chunks.

2. `research_analyst`
   - Owns document analysis, assertions, forecast extraction, graph/world-model updates, debate/agent analysis, quality gates, and dispatch batch export.

3. `research_dispatcher`
   - Owns cross-document through-lines, PM-facing narrative synthesis, callouts, calendar/supply context, report formatting, PDF/email delivery, and dispatch run history.

The weak contract is not "which repo owns analysis." That is already mostly correct. The weak contract is evidence addressability across the handoffs.

Parser should supply stable source span keys. Analyst should preserve and enrich those keys through chunks, evidence units, assertions, forecasts, world edges, and trading opportunities. Dispatcher should carry enough of those keys or compact citations to make through-lines traceable back to source evidence without bloating prompts.

## Schema Assessment

The current schema is directionally appropriate, but it should be treated as incomplete until evidence addressability is wired through the whole pipeline.

What is already appropriate:

- `parsed_research` remains a useful compatibility and archival row.
- Normalized `research_themes` and `research_theme_excerpts` are useful for current analyst hydration and dispatcher fallback.
- The additive `research_memory` migration has the right core primitives: document artifacts, spans, retrieval chunks, evidence units, entities, claims, relations, and events.
- `research_analyst` has a sensible local ownership model for run state, chunks, evidence units, assertions, world nodes/edges, forecast candidates, debate artifacts, and document analysis payloads.
- `research_dispatcher` has a reasonable run/snapshot schema for report production history.

What should be considered:

1. Wire and harden parser source spans before adding more high-level parser tables.
   - The schema already has `research_spans` and `research_retrieval_chunks`; the gap is live writes and downstream hydration.

2. Add source-span references to parser theme excerpts.
   - `research_theme_excerpts` currently stores excerpt text and ordering only. Add `span_key`, `chunk_key`, `page_ref`, or `source_ref` so existing analyst hydration can preserve provenance without a large redesign.

3. Normalize or evidence-link trades enough for querying.
   - Trades remain mostly JSONB in `parsed_data`. If trades drive reports and recommendations, they need either a normalized `research_trades` table or analyst-owned trade/opportunity records with evidence keys.

4. Decide where claims/entities/relations live.
   - Parser migration includes `research_claims`, `research_entities`, and `research_relations`, while analyst already has local assertion/world-model tables. Avoid two active authorities. Prefer parser-owned source/evidence primitives and analyst-owned semantic claims/world state unless there is a deliberate promotion path.

5. Add stable cross-repo key fields to analyst exports.
   - Analyst batch payloads should eventually include evidence keys, span keys, parser theme ids, assertion keys, and chunk keys where available, so dispatcher can trace through-lines back to source evidence.

6. Add FTS/vector indexing support explicitly.
   - `research_retrieval_chunks` has embedding metadata fields but no stored vector column or full-text index in the current migration. If Supabase/Postgres is the retrieval surface, add `tsvector`/GIN and/or `pgvector` once the retrieval strategy is chosen.

7. Version every derived layer.
   - Parser spans already have `span_version`; retrieval chunks have `chunker_version`; claims have extractor/resolver versions. The normalized theme/trade paths should also expose extraction version/model/prompt metadata if they become long-term query surfaces.

8. Preserve dispatcher snapshots with citation metadata.
   - Dispatcher snapshots currently store payload JSON, which is fine. Once evidence keys flow through, snapshots should retain the compact citation map used to produce each through-line/callout.

Schema bottom line:

The schema does not need a wholesale redesign. It needs a contract tightening around provenance:

- source span identity
- retrieval chunk identity
- evidence identity
- derived object identity
- versioning
- cross-repo propagation of those keys

Without that, the schemas will continue to support report generation, but higher-quality querying and auditability will remain weaker than the repo architecture otherwise allows.

## Open Follow-Up

Potential implementation plan should start at the parser-to-analyst contract: source spans, chunk keys, evidence keys, and compatibility behavior for legacy rows.
