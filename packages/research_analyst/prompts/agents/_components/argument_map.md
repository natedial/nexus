## Per-document argument map (the author's case)

Extract the author's argument the way an analyst takes notes: list the **main claims** the author makes, and for each claim record the **rationale** (the author's reasoning) and the **evidence** (the concrete support the author cites).

This is single-author extraction. There is **no agreement/disagreement here** — that is a cross-document operation built later by comparing these maps across authors. Do not add your own claims, and do not import counter-arguments from other notes.

### `argument_map[]` — `ClaimNode`

```
{
  "claim": "<a main argument the author makes, atomic>",
  "claim_type": "observation|forecast|causal|market_impact|policy|risk|recommendation",
  "stance": "<direction if applicable: bullish|bearish|neutral|... or null>",
  "horizon": "<the timeframe the claim is about, if the author gives one: 'Q2 2026', 'H2', '12m', or null>",
  "rationale": "<the author's reasoning: WHY the claim follows — the logic linking evidence to claim>",
  "evidence": [
    {
      "text": "<the concrete support the author cites: a datapoint, quote, chart, prior event>",
      "kind": "data|quote|citation|chart|prior_view",
      "ref_key": "<assertion_key|evidence_key|chunk_id|span_key>"
    }
  ],
  "conditions": ["<caveat or condition the author attaches, if any>"],
  "support_strength": "evidenced|reasoned|asserted"
}
```

### Rationale is not evidence

- **Evidence** is a verifiable thing the author points to — a number, a chart, a quote, a named prior event or source. It carries a real `ref_key`.
- **Rationale** is the author's reasoning that links that evidence to the claim. It is logic, not a datapoint.
- **`support_strength`** is your read on how well the author actually backs the claim:
  - `evidenced` — backed by cited data/quotes (requires ≥ 1 grounded `evidence`).
  - `reasoned` — argued logically but with no hard data.
  - `asserted` — stated without support. Label it honestly; do not manufacture evidence to upgrade it.

### Worked example

```json
{
  "argument_map": [
    {
      "claim": "the Fed is done hiking",
      "claim_type": "forecast",
      "stance": "dovish",
      "horizon": null,
      "rationale": "Removing the final projected hike signals the terminal rate is set; with services disinflation underway, further tightening would over-restrict.",
      "evidence": [
        {"text": "December dots removed the final projected hike", "kind": "data", "ref_key": "assertion:chunk-2:1"},
        {"text": "3-month annualized services CPI is decelerating", "kind": "data", "ref_key": "assertion:chunk-5:0"}
      ],
      "conditions": ["holds unless core services re-accelerates"],
      "support_strength": "evidenced"
    },
    {
      "claim": "first cut comes in Q2",
      "claim_type": "forecast",
      "stance": "dovish",
      "horizon": "Q2 2026",
      "rationale": "The dot median implies an earlier move than the market prices.",
      "evidence": [
        {"text": "median 2026 funds-rate dot at 3.9%", "kind": "data", "ref_key": "assertion:chunk-2:2"}
      ],
      "conditions": [],
      "support_strength": "reasoned"
    }
  ]
}
```

### Rules

- **Emit between 3 and 7 claims.** Capture the author's load-bearing arguments, not every sentence. If the note genuinely makes fewer than 3 arguments, emit fewer — do not pad.
- One contention per `claim`, kept atomic, so the claim can be matched or contrasted against other authors point-for-point.
- Set `horizon` whenever the author attaches a timeframe. Two authors often share a conclusion and split only on timing; without the timeframe that split is invisible.
- Every `evidence` entry needs a real `ref_key` (`corpus` passages use the `research_search` `chunk_id`). Supply the provenance `ref_key` only — a downstream resolver maps it to the canonical fact/event it refers to, which is what lets the same evidence be compared across authors. Accurate provenance here is what makes that resolution possible.
- Capture only what the author argues; if the author asserts something without support, keep it and mark `support_strength: "asserted"` rather than dropping it or inventing evidence.
