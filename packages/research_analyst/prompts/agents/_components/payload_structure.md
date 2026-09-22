## Input payload structure

The first user message is a JSON object — not raw document text. Parse it and use the richest available signal. Structure:

```json
{
  "agent_type": "<string>",
  "document": {
    "research_id": <int>,
    "file_id": "<drive/file id or null>",
    "document_hash": "<sha256 or null>",
    "document_name": "<filename>",
    "document_title": "<string or null>",
    "source": "<publisher code or null>",
    "source_date": "<YYYY-MM-DD or null>",
    "publisher": "<string or null>",
    "area": "<macro | rates | fx | ... | null>",
    "region": "<string or null>",
    "asset_focus": "<string or null>",
    "document_link": "<url or null>",
    "trade_count": <int>,
    "theme_count": <int>,
    "identity": {"<key>": "<json-safe value>", "...": "..."},
    "metadata": {"<key>": "<json-safe value>", "...": "..."},
    "full_text_excerpt": "<up to 12k chars, may be truncated with ...>"
  },
  "themes": [
    {
      "theme_id": <int>,
      "theme_key": "<theme-{id} or null>",
      "theme_order": <int>,
      "label": "<short theme name>",
      "scope": "<string or null>",
      "primary_category": "<string or null>",
      "relevance": ["<tag>", "..."],
      "classification": "<string>",
      "strength": "<string>",
      "confidence": "<string label from parser>",
      "evidence_count": <int>,
      "mention_count": <int>,
      "context": "<up to 1.2k chars>",
      "directionality": {"<key>": "<json-safe value>", "...": "..."} | null,
      "argument_structure": {"<key>": "<json-safe value>", "...": "..."} | null,
      "excerpts": ["<excerpt>", "..."]
    }
  ],
  "deterministic_analysis": {
    "chunks": [
      {
        "chunk_order": <int>,
        "chunk_key": "<chunk-{order} or null>",
        "chunk_type": "<string>",
        "title": "<string>",
        "text": "<up to 900 chars>",
        "section_name": "<string or null>",
        "topic_tags": ["<tag>", "..."],
        "entity_tags": ["<entity>", "..."],
        "horizon_tag": "<string or null>",
        "parser_theme_id": <int or null>,
        "span_keys": ["<span_key>", "..."],
        "retrieval_chunk_key": "<string or null>"
      }
    ],
    "evidence_units": [
      {
        "chunk_order": <int>,
        "chunk_key": "<chunk-{order} or null>",
        "evidence_order": <int>,
        "evidence_key": "<chunk-{order}:evidence-{evidence_order} or null>",
        "evidence_type": "<string>",
        "text": "<up to 400 chars>",
        "normalized_text": "<up to 400 chars or null>",
        "page_ref": "<string or null>",
        "source_ref": {"<key>": "<json-safe value>", "...": "..."},
        "parser_theme_id": <int or null>
      }
    ],
    "assertions": [
      {
        "chunk_order": <int>,
        "chunk_key": "<chunk-{order} or null>",
        "assertion_order": <int>,
        "assertion_key": "<chunk-{order}:assertion-{assertion_order} or null>",
        "assertion_type": "<claim|forecast|risk|...>",
        "text": "<up to 500 chars>",
        "summary_text": "<up to 500 chars>",
        "polarity": "<positive|negative|neutral|not_applicable>",
        "confidence_label": "<low|medium|high>",
        "extraction_confidence": "<low|medium|high>",
        "time_horizon": "<intraday|days|weeks|months|longer|unknown>",
        "time_anchor": "<string or null>",
        "condition_text": "<string or null>",
        "qualifier_text": "<string or null>",
        "status": "<proposed|supported|contested|unknown>",
        "authority_band": "<low|medium|high|seed>",
        "subject_text": "<string or null>",
        "object_text": "<string or null>"
      }
    ],
    "figures": [
      {
        "figure_key": "<figure:{content_hash[:16]}>",
        "label": "<fig_001 display label>",
        "page": <int or null>,
        "caption": "<caption text>"
      }
    ]
  }
}
```

**Use the pre-extracted signal.** `deterministic_analysis.assertions` is already typed with polarity, time horizon, authority, and stable `assertion_key`s — do not re-derive these from the excerpt. Cite `span_key` from `chunks[].span_keys` or `evidence_units[].source_ref.span_key` — do not invent theme labels. Cite a chart with `figures[].figure_key`. `themes[]` is an optional extraction overlay and is often empty. Reach for `document.full_text_excerpt` only when assertions, chunks, and themes are silent on a point you need.

## Empty-payload fallback

Not every parser run produces rich signal. Before working, check the payload and follow this ladder:

1. If `deterministic_analysis.assertions[]` is non-empty, use it as your primary source.
2. Else if `deterministic_analysis.chunks[]` is non-empty, work from chunk text and cite `span_keys` / `source_ref.span_key`.
3. Else if `themes[]` is non-empty, work from `themes[].excerpts[]` and `themes[].context`.
4. Else if `document.full_text_excerpt` is a non-empty string, read it directly.
5. Else — all four are empty — do not fabricate analysis. Return a single summary sentence stating that the document lacks analyzable content, leave `key_claims` empty, and set `confidence` to `0.0`. This is the correct, honest outcome; downstream consumers filter by confidence.

Do not mix ladder rungs. If rung 1 is available, do not also reach to rung 4 "for color" — it just adds noise and hurts reproducibility.
