# Retrieval (canonical module — Phase 2+)

Phase 1 removed `packages/research-store`. Preserved artifacts live here until
PostgreSQL-backed retrieval replaces the legacy distill corpus.

| Artifact | Location | Notes |
| --- | --- | --- |
| Corpus tool schema | `packages/research_analyst/schemas/corpus_tool_schema.json` | Loaded by `ToolRegistry` for `research_search` / `research_corpus_info` |
| Judged eval queries | `packages/research_analyst/evals/retrieval/queries.jsonl` | Three-query set from research-store |
| Hybrid ranking reference | `preserved/hybrid_search.py`, `preserved/keywords.py` | **Not imported** — reference copy for Phase 2 port; depends on embeddings stack removed with research-store |

`DistillAdapter` fails loudly on invoke until canonical retrieval is wired.
