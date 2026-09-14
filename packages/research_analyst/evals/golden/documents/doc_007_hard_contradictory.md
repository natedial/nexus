# Document: DB Rates - Hard Case (Contradictory)

## Metadata
- source: Deutsche Bank
- source_date: 2026-04-11
- area: USD
- asset_focus: rates

## Full Text Excerpt

**US Rates: Conflicting Signals**

This document presents a genuinely ambiguous outlook. We see compelling arguments on both sides of the rate debate.

**Bull Case for Rates Falling:**

- Inflation trending lower: Core PCE at 2.5% and falling
- Labor market showing cracks: Initial claims trending up, hiring plans declining
- Manufacturing recession signals: PMI below 50 for third consecutive month
- Housing market softening: Existing home sales down 8% YoY

**Bear Case for Rates Staying High:**

- Services inflation sticky: Core services PCE at 3.2%, not declining
- Wages still elevated: ECI at 4.2% YoY
- Consumer spending resilient: Retail sales +0.6% MoM
- Fed pushback: Multiple officials recently emphasized patience

**The Data:**

| Indicator | Current | 6M Ago | Direction |
|-----------|---------|--------|-----------|
| Core PCE | 2.5% | 2.8% | ↓ |
| Core Services | 3.2% | 3.1% | ↑ |
| Unemployment | 4.2% | 3.8% | ↑ |
| Wage Growth | 4.2% | 4.0% | ↑ |
| Retail Sales | +0.6% | +0.3% | ↑ |
| ISM Mfg | 47.8 | 49.5 | ↓ |

**Our Assessment:**

We confess genuine uncertainty. The soft landing narrative is intact but showing stress. The data does not clearly favor either direction.

We recommend:
- Reduce duration risk
- Stay flexible
- Wait for clearer signals

If forced to choose, we lean slightly toward a shallower cuts path (2 x 25bp vs 3 x 25bp), but acknowledge this could easily be wrong.

---

## Themes (from parser)

```json
[
  {
    "label": "Conflicting signals",
    "scope": "Macro",
    "primary_category": "Rates",
    "classification": "Description",
    "strength": "Primary",
    "context": "Genuinely ambiguous outlook with compelling arguments both ways",
    "directionality": null
  },
  {
    "label": "Inflation diverging",
    "scope": "Macro",
    "primary_category": "Rates",
    "classification": "Description",
    "strength": "Primary",
    "context": "Goods inflation falling, services inflation sticky",
    "directionality": null
  },
  {
    "label": "Shallow cuts base case",
    "scope": "Policy",
    "primary_category": "Rates",
    "classification": "Forecast",
    "strength": "Secondary",
    "context": "2 x 25bp vs 3 x 25bp, acknowledge uncertainty",
    "directionality": {"bullish": 1}
  }
]
```

## Assertions (from parser)

```json
[
  {
    "text": "Core PCE at 2.5% and falling",
    "polarity": "positive",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "Inflation",
    "object_text": "declining"
  },
  {
    "text": "Services inflation sticky at 3.2%",
    "polarity": "negative",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "Services inflation",
    "object_text": "elevated"
  },
  {
    "text": "Genuine uncertainty",
    "polarity": "neutral",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "Outlook",
    "object_text": "ambiguous"
  },
  {
    "text": "Lean toward 2 x 25bp cuts",
    "polarity": "positive",
    "time_horizon": "months",
    "authority_band": "low",
    "subject_text": "Fed",
    "object_text": "cuts"
  }
]
```
