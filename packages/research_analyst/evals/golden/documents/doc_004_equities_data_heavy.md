# Document: MS Equities - Data Heavy

## Metadata
- source: Morgan Stanley
- source_date: 2026-04-09
- area: USD
- asset_focus: equities

## Full Text Excerpt

**US Equity Strategy - Quantitative Analysis**

We present comprehensive data analysis across valuation, momentum, and fundamental metrics.

**Valuation Metrics:**

| Metric | Current | 10Y Avg | Z-Score |
|--------|---------|---------|---------|
| S&P 500 P/E (fwd) | 21.3x | 18.5x | +1.2σ |
| S&P 500 P/E (trailing) | 24.8x | 21.2x | +1.1σ |
| Equity risk premium | 2.1% | 3.2% | -1.4σ |
| CAPE ratio | 33.4 | 28.1 | +1.0σ |

**Earnings Analysis:**

- Q1 2026 EPS growth: +8.2% YoY (vs +6.5% expected)
- Q2 2026 consensus: +7.1% YoY
- 2026 full-year EPS: $258 (up from $245 prior)
- Margins at 12.4%, near cycle highs

**Technical Indicators:**

- 50-day MA: 5120
- 200-day MA: 4980
- Current: 5185
- Trend: Bullish, above both MAs

**Sector Performance YTD:**

| Sector | Return | vs SPX |
|--------|--------|---------|
| Tech | +14.2% | +4.1% |
| Consumer | +8.5% | -1.6% |
| Financials | +7.2% | -2.9% |
| Healthcare | +5.8% | -4.3% |
| Energy | +2.1% | -8.0% |

**Positioning Data:**

- AAII bulls: 42% (10Y high)
- Put/call ratio: 0.65 (low)
- Hedge fund net exposure: 78% (high)
- CTA trend: Long $12B

**Risk Factors:**

1. Valuation premium to historical averages
2. Earnings beats may be priced in
3. Seasonal headwinds in Q2 (post-earnings)

**Conclusion:**

While fundamentals remain solid, valuations leave little room for disappointment. Maintain overweight but rotate into defensive sectors. Target S&P 500: 5200 by Q2.

---

## Themes (from parser)

```json
[
  {
    "label": "Valuation premium",
    "scope": "Asset",
    "primary_category": "Equities",
    "classification": "Description",
    "strength": "Primary",
    "context": "P/E at 21.3x fwd, 1.2 sigma above 10Y average",
    "directionality": null
  },
  {
    "label": "Solid earnings growth",
    "scope": "Macro",
    "primary_category": "Equities",
    "classification": "Description",
    "strength": "Primary",
    "context": "Q1 EPS +8.2% YoY, full year $258",
    "directionality": {"bullish": 1}
  },
  {
    "label": "Rotate to defensive",
    "scope": "Positioning",
    "primary_category": "Equities",
    "classification": "Opinion",
    "strength": "Primary",
    "context": "Maintain OW but rotate into defensive sectors",
    "directionality": null
  }
]
```

## Assertions (from parser)

```json
[
  {
    "text": "S&P 500 P/E 21.3x forward",
    "polarity": "neutral",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "S&P 500",
    "object_text": "valuation"
  },
  {
    "text": "Q1 EPS growth +8.2%",
    "polarity": "positive",
    "time_horizon": "weeks",
    "authority_band": "high",
    "subject_text": "Earnings",
    "object_text": "growth"
  },
  {
    "text": "Target 5200 by Q2",
    "polarity": "positive",
    "time_horizon": "months",
    "authority_band": "medium",
    "subject_text": "S&P 500",
    "object_text": "price target"
  }
]
```
