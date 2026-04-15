# Document: JPM Credit

## Metadata
- source: J.P. Morgan
- source_date: 2026-04-04
- area: USD
- asset_focus: credit

## Full Text Excerpt

**Credit Market Update: Spreads Tight but Fundamentals Soften**

IG and HY spreads have compressed to cycle lows. We remain constructive but acknowledge reduced buffer against adverse events.

**Market Overview:**

| Segment | Spread (bp) | 10Y Avg | Z-Score |
|---------|-------------|----------|---------|
| IG | 95 | 145 | -1.2 |
| HY | 285 | 425 | -1.0 |
| Loans | 425 | 520 | -0.8 |

**Fundamentals:**

- Leverage at 3.8x (up from 3.5x in 2023)
- Interest coverage at 4.5x (down from 6.0x)
- Refinancing wall: $1.2T in 2026-2027
- Default rate forecast: 3.5% (up from 2.0%)

**Technical Support:**

- Flows: $15B into credit funds YTD
- New issuance: Light calendar, technical demand
- CLO formation: Robust, supporting loan demand

**Our Positioning:**

We remain OW credit but with caution. Recommendations:

1. **IG**: Prefer short-duration (2-5Y) within the index
2. **HY**: Stay BB-rated, avoid CCC
3. **Loans**: Reduce exposure, refinancing risk elevated

The macro backdrop supports credit, but valuation leaves no room for disappointment.

---

## Themes (from parser)

```json
[
  {
    "label": "Cycle low spreads",
    "scope": "Macro",
    "primary_category": "Credit",
    "classification": "Description",
    "strength": "Primary",
    "context": "IG at 95bp, HY at 285bp - below 10Y average",
    "directionality": null
  },
  {
    "label": "Fundamentals weakening",
    "scope": "Macro",
    "primary_category": "Credit",
    "classification": "Description",
    "strength": "Primary",
    "context": "Leverage up, interest coverage down, refinancing wall ahead",
    "directionality": {"bearish": 1}
  },
  {
    "label": "OW but cautious",
    "scope": "Positioning",
    "primary_category": "Credit",
    "classification": "Opinion",
    "strength": "Primary",
    "context": "Prefer short-duration IG, stay BB in HY",
    "directionality": null
  }
]
```

## Assertions (from parser)

```json
[
  {
    "text": "IG spread 95bp",
    "polarity": "neutral",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "IG",
    "object_text": "spreads"
  },
  {
    "text": "Leverage at 3.8x",
    "polarity": "negative",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "Corporate",
    "object_text": "leverage"
  },
  {
    "text": "Default rate 3.5%",
    "polarity": "negative",
    "time_horizon": "months",
    "authority_band": "medium",
    "subject_text": "HY",
    "object_text": "defaults"
  },
  {
    "text": "Prefer short-duration IG",
    "polarity": "positive",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "IG",
    "object_text": "positioning"
  }
]
```
