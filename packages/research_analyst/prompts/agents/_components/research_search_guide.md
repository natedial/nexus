## Using `research_search`

The `research_search` tool retrieves passages from the broader research corpus. Call it only when you need context beyond this document — not to paraphrase what the document already contains.

Parameters:
- `query` (string, required) — a short focused phrase, not a question. Good: `"Fed December dot plot 2025"`. Bad: `"What did the Fed say about rate cuts?"`.
- `date_from` (YYYY-MM-DD, optional) — default to 90 days before `document.source_date` unless you are explicitly looking for a historical parallel.
- `date_to` (YYYY-MM-DD, optional) — default to the `document.source_date`.
- `limit` (int, optional) — default 5. Prefer 3 for targeted lookups.

Search strategy:
1. Before searching, ask whether the document already answers the question. If yes, do not search.
2. Prefer one or two focused queries over many broad ones.
3. When a returned passage is relevant, include it in `cross_document_refs` with the exact `chunk_id`, `source_path`, `source_date`, truncated `text`, and `relevance_score` the tool returned — do not paraphrase or invent these fields.

## When the tool returns no results

Empty results are a real signal, not a failure. If your first query comes back with zero passages:

1. **Do not immediately retry with a broader query.** A single empty result after a tight query is expected; a broad retry wastes budget and often returns noise.
2. Note the empty result in your `risks` list (e.g. `"no corroborating corpus passages found for <subject>"`).
3. Lower the `confidence` on any claim that depended on corpus support by at least `0.10`.
4. Retry only if your original query was bounded by a narrow `date_from`/`date_to` window and widening the window to the last 180 days is clearly warranted.

Budget guidance is set per-agent. Spend it on the highest-leverage lookups first.
