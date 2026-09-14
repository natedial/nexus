## Output sub-schemas (synthesizer only)

The synthesizer emits three lists that downstream consumers read directly. Each item must conform to the schema below. Emit items only when the document supports them — **prefer an empty list over low-confidence items**.

### `trading_opportunities[]` — `TradingOpportunity`

```
{
  "thesis": "<string, max 100 chars>",
  "direction": "long" | "short" | "neutral",
  "instrument": "<e.g. EUR/USD, 10Y Treasury, NASDAQ, Gold>",
  "timeframe": "intraday" | "days" | "weeks",
  "conviction": "high" | "medium" | "low",
  "risk_reward_ratio": "<e.g. 1:2, or null>",
  "key_levels": "<entry/stop/target levels, or null>",
  "rationale": "<string, max 200 chars>",
  "supporting_excerpts": ["<quoted passage>", "..."],
  "risks": ["<risk to this trade>", "..."]
}
```

Worked example:

```json
{
  "thesis": "Fed pause supports curve steepener",
  "direction": "long",
  "instrument": "2s10s UST curve",
  "timeframe": "weeks",
  "conviction": "medium",
  "risk_reward_ratio": "1:2",
  "key_levels": "entry 35bp, stop 25bp, target 55bp",
  "rationale": "Dovish dots + sticky services CPI argue for bear steepening",
  "supporting_excerpts": ["...projected median funds rate of 3.9% for 2026..."],
  "risks": ["Surprise hot NFP could re-flatten", "Auction tailwind risk"]
}
```

### `short_time_horizon_insights[]` — `ShortTimeHorizonInsight`

```
{
  "theme": "<string, max 50 chars>",
  "insight": "<string, max 300 chars>",
  "timeframe_ref": "intraday" | "days" | "weeks",
  "confidence": "high" | "medium" | "low",
  "supporting_excerpt": "<quoted passage>",
  "relevance": ["<tag>", "..."]
}
```

### `talking_points[]` — `TalkingPoint`

```
{
  "text": "<string, max 500 chars — the quotable line>",
  "context": "<string, max 200 chars — what surrounds it>",
  "source_theme": "<short theme name or null>",
  "presentation_use": "headline" | "supporting" | "footnote",
  "target_audience": "internal" | "client" | "all" | null
}
```

**Provenance rule:** every `supporting_excerpt` / `supporting_excerpts[]` / `text` must be a verbatim or near-verbatim excerpt from `base.document.full_text_excerpt`, `base.themes[].excerpts[]`, or `base.deterministic_analysis.chunks[].text`. Do not invent quotes.
