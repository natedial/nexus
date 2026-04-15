# Document: MS EUR Rates

## Metadata
- source: Morgan Stanley
- source_date: 2026-04-03
- area: EUR
- asset_focus: rates

## Full Text Excerpt

**Eurozone Rates: Dovish Shift, But How Much?**

The ECB has shifted dovish, but markets are pricing excessive cuts. We see only 50bp of cuts in 2026 vs 70bp priced.

**ECB Dynamics:**

- Governing Council now unified on gradual approach
- Inflation forecasts revised lower: 2.3% in 2026
- Growth outlook modest: 0.8% GDP

**Key Data:**

| Indicator | Current | Target |
|-----------|---------|--------|
| HICP | 2.4% | 2.0% |
| Core HICP | 2.9% | 2.0% |
| Wage growth | 4.8% | 2.0% |
| Unemployment | 6.5% | - |

**Market Implication:**

The euro swap curve is pricing 70bp of cuts. We think this is too much. Services inflation remains elevated at 3.0%, and wage growth shows no clear downward trend.

**Trade:**

We recommend receiving 6-month EURIBOR. Target: 3.00% (current 3.35%). This benefits from:
- Fewer cuts than priced
- Term premium recovery
- Carry advantage

---

## Themes (from parser)

```json
[
  {
    "label": "Excessive cut pricing",
    "scope": "Macro",
    "primary_category": "Rates",
    "classification": "Opinion",
    "strength": "Primary",
    "context": "70bp priced vs 50bp expected",
    "directionality": {"bullish": 1}
  },
  {
    "label": "Services inflation sticky",
    "scope": "Macro",
    "primary_category": "Rates",
    "classification": "Description",
    "strength": "Primary",
    "context": "Core HICP 2.9%, services 3.0%",
    "directionality": null
  },
  {
    "label": "Receive 6M EURIBOR",
    "scope": "Positioning",
    "primary_category": "Rates",
    "classification": "Opinion",
    "strength": "Primary",
    "context": "Target 3.00% (current 3.35%)",
    "directionality": {"bullish": 1}
  }
]
```

## Assertions (from parser)

```json
[
  {
    "text": "50bp cuts in 2026",
    "polarity": "neutral",
    "time_horizon": "months",
    "authority_band": "high",
    "subject_text": "ECB",
    "object_text": "cuts"
  },
  {
    "text": "70bp priced is too much",
    "polarity": "positive",
    "time_horizon": "weeks",
    "authority_band": "medium",
    "subject_text": "EUR rates",
    "object_text": "pricing"
  },
  {
    "text": "Target 3.00% on 6M EURIBOR",
    "polarity": "positive",
    "time_horizon": "months",
    "authority_band": "medium",
    "subject_text": "EURIBOR",
    "object_text": "rate target"
  }
]
```
