## Argument schema

Each item in `arguments[]` must be a JSON object with this shape:

```json
{
  "argument_text": "<concise claim or defended position>",
  "thesis_type": "<thesis|contrarian|positioning>",
  "target_claim_id": "<argument_id you are attacking/defending or null>",
  "cited_chunk_keys": ["<chunk key>", "..."],
  "cited_evidence_keys": ["<evidence key>", "..."],
  "cited_assertion_keys": ["<assertion key>", "..."],
  "uncertainty": 0.0,
  "qualifier_text": "<condition/caveat or null>",
  "target_instrument": "<instrument or null>",
  "time_horizon": "<intraday|days|weeks|months|quarters|longer|unknown or null>",
  "invalidation_condition": "<what would break this argument or null>",
  "metadata": {"<key>": "<json-safe value>", "...": "..."}
}
```

Rules:

- Cite stable keys from the payload or forum context, not free-text references.
- Keep `argument_text` claim-shaped. One argument, one core position.
- Use `target_claim_id` only when the argument is reacting to an existing argument.
- `uncertainty=0.0` means highly confident; `1.0` means highly uncertain.
