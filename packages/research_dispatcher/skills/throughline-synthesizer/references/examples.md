# Through-Line Synthesizer: Few-Shot Examples

This document provides complete input/output examples demonstrating proper through-line synthesis across different consensus levels and market scenarios.

---

## Example 1: Strong Consensus on Fed Policy

### Input

```json
{
  "themes": [
    {
      "source": "Goldman Sachs",
      "document": "GS Rates Weekly",
      "label": "Fed pivot timing",
      "context": "We expect the Fed to begin cutting rates in March 2025, with 75bp of easing by year-end. The labor market is cooling faster than consensus expects, and inflation is on a sustainable path to 2%.",
      "strength": "Primary",
      "confidence": "High"
    },
    {
      "source": "JPMorgan",
      "document": "JPM Interest Rate Derivatives",
      "label": "Fed easing cycle",
      "context": "Our base case is for the Fed to cut 25bp in March and continue quarterly thereafter. Core PCE trajectory supports earlier action than the market currently prices.",
      "strength": "Primary",
      "confidence": "High"
    },
    {
      "source": "Barclays",
      "document": "Barclays US Rates Strategy",
      "label": "FOMC policy path",
      "context": "We see the Fed cutting 75bp in 2025, starting in Q1. The employment mandate is now the binding constraint, and real rates are too restrictive for a soft landing.",
      "strength": "Primary",
      "confidence": "High"
    },
    {
      "source": "Morgan Stanley",
      "document": "MS Global Rates Radar",
      "label": "Treasury curve normalization",
      "context": "As the Fed easing cycle begins, we expect the 2s10s curve to steepen by 50-75bp over the next 6 months. Front-end rates will reprice faster than the long end.",
      "strength": "Secondary",
      "confidence": "Medium"
    }
  ],
  "trades": [
    {
      "source": "Goldman Sachs",
      "document": "GS Rates Weekly",
      "text": "Receive 5Y SOFR at 3.85%, target 3.50%, stop 4.05%",
      "conviction": "High",
      "timeframe": "months"
    },
    {
      "source": "JPMorgan",
      "document": "JPM Interest Rate Derivatives",
      "text": "2s10s steepeners via swaps, entry at -25bp, target +25bp",
      "conviction": "High",
      "timeframe": "months"
    }
  ],
  "document_count": 6,
  "date_range": "2025-01-20 to 2025-01-27"
}
```

### Output

```json
{
  "title": "Fed pivot consensus builds as dealers align on Q1 cut timing and curve steepening",
  "document_count": 6,
  "through_lines": [
    {
      "lead": "Three major dealers converge on March Fed cut as employment data softens and inflation normalizes",
      "supporting_sources": ["Goldman Sachs", "JPMorgan", "Barclays"],
      "consensus_level": "strong_consensus",
      "supporting_themes": ["Fed pivot timing", "Fed easing cycle", "FOMC policy path"],
      "supporting_trades": ["Receive 5Y SOFR at 3.85%, target 3.50%, stop 4.05%"],
      "key_insight": "Goldman Sachs, JPMorgan, and Barclays all project 75bp of Fed cuts in 2025 beginning in Q1, with March as the most likely start date. The mechanism is shared: labor market cooling is now the binding constraint, with real rates viewed as too restrictive for a soft landing. This consensus is notable for its specificity on timing and magnitude. Goldman's 5Y receiver at 3.85% offers a direct expression of this view with defined risk parameters."
    },
    {
      "lead": "Curve steepening trades gain support as Fed pivot reprices the front end faster than the long end",
      "supporting_sources": ["Morgan Stanley", "JPMorgan"],
      "consensus_level": "moderate_consensus",
      "supporting_themes": ["Treasury curve normalization"],
      "supporting_trades": ["2s10s steepeners via swaps, entry at -25bp, target +25bp"],
      "key_insight": "Morgan Stanley and JPMorgan both favor curve steepening as the second-order effect of Fed easing. MS projects 50-75bp of 2s10s steepening over 6 months, while JPM's trade targets a 50bp move from current levels. The transmission is straightforward: front-end rates are more sensitive to Fed policy, while the long end is anchored by term premium and supply dynamics. JPM's swap entry at -25bp provides a specific execution level."
    }
  ],
  "callouts": [
    {
      "text": "Goldman Sachs, JPMorgan, and Barclays all project 75bp of Fed cuts in 2025 starting in Q1, with labor market cooling as the shared catalyst and March as the consensus start date.",
      "source_through_line": "Three major dealers converge on March Fed cut as employment data softens and inflation normalizes"
    },
    {
      "text": "Morgan Stanley and JPMorgan favor 2s10s steepeners, with MS targeting 50-75bp of normalization as front-end rates reprice faster than the long end during the Fed pivot.",
      "source_through_line": "Curve steepening trades gain support as Fed pivot reprices the front end faster than the long end"
    }
  ]
}
```

---

## Example 2: Mixed Views on ECB Policy

### Input

```json
{
  "themes": [
    {
      "source": "Citi",
      "document": "Citi European Rates Outlook",
      "label": "ECB cutting cycle",
      "context": "We expect the ECB to cut 25bp in April, with 100bp of easing by year-end. Growth is the dominant concern, and inflation is back to target faster than the Governing Council anticipated.",
      "strength": "Primary",
      "confidence": "High"
    },
    {
      "source": "Barclays",
      "document": "Barclays Euro Rates Weekly",
      "label": "ECB policy caution",
      "context": "The ECB will proceed cautiously despite weak growth. We see only 50bp of cuts in 2025, with the first move in June. Services inflation remains sticky, and the Governing Council wants to avoid premature easing.",
      "strength": "Primary",
      "confidence": "Medium"
    },
    {
      "source": "Deutsche Bank",
      "document": "DB European Macro Strategy",
      "label": "German recession risk",
      "context": "Germany is likely in a technical recession, which will force the ECB's hand. We expect 75bp of cuts starting in April, regardless of services inflation readings.",
      "strength": "Primary",
      "confidence": "High"
    },
    {
      "source": "BNP Paribas",
      "document": "BNPP Rates Navigator",
      "label": "Bund supply dynamics",
      "context": "Heavy Bund supply in Q2 will create headwinds for duration, even as the ECB cuts. We expect the Bund curve to bear steepen as issuance overwhelms easing expectations.",
      "strength": "Secondary",
      "confidence": "Medium"
    }
  ],
  "trades": [
    {
      "source": "Citi",
      "document": "Citi European Rates Outlook",
      "text": "Long Schatz, receive 2Y EUR swaps at 2.60%",
      "conviction": "High",
      "timeframe": "weeks"
    },
    {
      "source": "BNP Paribas",
      "document": "BNPP Rates Navigator",
      "text": "10s30s Bund steepeners, entry at 35bp, target 55bp",
      "conviction": "Medium",
      "timeframe": "months"
    }
  ],
  "document_count": 5,
  "date_range": "2025-01-20 to 2025-01-27"
}
```

### Output

```json
{
  "title": "ECB path divides dealers: doves see April cut, hawks argue for June as services inflation lingers",
  "document_count": 5,
  "through_lines": [
    {
      "lead": "Sources split on ECB timing with 50bp gap between dovish and hawkish projections for 2025 easing",
      "supporting_sources": ["Citi", "Barclays", "Deutsche Bank"],
      "consensus_level": "mixed_views",
      "supporting_themes": ["ECB cutting cycle", "ECB policy caution", "German recession risk"],
      "supporting_trades": ["Long Schatz, receive 2Y EUR swaps at 2.60%"],
      "key_insight": "Dealers are materially divided on ECB policy. Citi and Deutsche Bank expect 75-100bp of cuts starting in April, driven by growth weakness and Germany's technical recession. Barclays counters with only 50bp and a June start, citing sticky services inflation and Governing Council caution. This divergence creates two-way risk around ECB meetings. Citi's Schatz longs express the dovish view but are vulnerable if Barclays is right about inflation persistence."
    },
    {
      "lead": "Bund supply in Q2 may offset ECB easing benefits, creating bear steepening risk in the curve",
      "supporting_sources": ["BNP Paribas"],
      "consensus_level": "contrarian",
      "supporting_themes": ["Bund supply dynamics"],
      "supporting_trades": ["10s30s Bund steepeners, entry at 35bp, target 55bp"],
      "key_insight": "BNP Paribas raises an underappreciated headwind: heavy Bund issuance in Q2 could overwhelm the positive duration effect of ECB cuts. Their 10s30s steepener trade at 35bp entry expresses the view that long-end Bunds will underperform even in an easing cycle. This is worth monitoring as a hedge against consensus duration longs if supply calendars confirm elevated issuance."
    }
  ],
  "callouts": [
    {
      "text": "Citi sees 100bp of ECB cuts starting April; Barclays expects only 50bp from June, citing services inflation persistence. This 50bp divergence creates material two-way risk around ECB meetings.",
      "source_through_line": "Sources split on ECB timing with 50bp gap between dovish and hawkish projections for 2025 easing"
    },
    {
      "text": "BNP Paribas flags Q2 Bund supply as an underappreciated headwind that could force bear steepening even as the ECB cuts, recommending 10s30s steepeners at 35bp entry.",
      "source_through_line": "Bund supply in Q2 may offset ECB easing benefits, creating bear steepening risk in the curve"
    }
  ]
}
```

---

## Example 3: Contrarian View on BoJ Policy

### Input

```json
{
  "themes": [
    {
      "source": "Goldman Sachs",
      "document": "GS Japan Rates",
      "label": "BoJ normalization path",
      "context": "The BoJ will maintain its gradual normalization stance, with the next rate hike likely in Q2. JGB 10Y yields should remain range-bound between 0.9% and 1.1%.",
      "strength": "Primary",
      "confidence": "Medium"
    },
    {
      "source": "JPMorgan",
      "document": "JPM Asia Rates Weekly",
      "label": "JGB curve dynamics",
      "context": "We expect the JGB curve to remain relatively flat as the BoJ continues gradual policy adjustment. YCC removal has been well-telegraphed and should not cause significant volatility.",
      "strength": "Secondary",
      "confidence": "Medium"
    },
    {
      "source": "Morgan Stanley",
      "document": "MS Global Rates Radar",
      "label": "BoJ surprise risk",
      "context": "Markets are underpricing the risk of a BoJ policy shift in Q1. Wage data is coming in stronger than expected, and the yen's weakness may force the BoJ to act sooner. We see 10Y JGB yields testing 1.3% by March.",
      "strength": "Primary",
      "confidence": "High"
    }
  ],
  "trades": [
    {
      "source": "Morgan Stanley",
      "document": "MS Global Rates Radar",
      "text": "Short 10Y JGB futures, entry 144.50, target 142.00, stop 145.50",
      "conviction": "Medium",
      "timeframe": "weeks"
    }
  ],
  "document_count": 4,
  "date_range": "2025-01-20 to 2025-01-27"
}
```

### Output

```json
{
  "title": "BoJ policy consensus faces MS challenge as wage data and yen weakness could accelerate normalization",
  "document_count": 4,
  "through_lines": [
    {
      "lead": "Goldman and JPMorgan expect gradual BoJ normalization, but Morgan Stanley sees underpriced Q1 policy shift risk",
      "supporting_sources": ["Goldman Sachs", "JPMorgan", "Morgan Stanley"],
      "consensus_level": "mixed_views",
      "supporting_themes": ["BoJ normalization path", "JGB curve dynamics", "BoJ surprise risk"],
      "supporting_trades": ["Short 10Y JGB futures, entry 144.50, target 142.00, stop 145.50"],
      "key_insight": "Goldman Sachs and JPMorgan share a consensus view of gradual BoJ normalization with Q2 as the next likely hike window and JGB 10Y remaining range-bound. Morgan Stanley explicitly challenges this, arguing that strong wage data and yen weakness could force earlier action. MS projects 10Y yields testing 1.3% by March versus GS's 1.1% cap. The MS short JGB futures trade at 144.50 provides a direct expression with defined risk."
    },
    {
      "lead": "Morgan Stanley's contrarian JGB bearishness warrants monitoring as wage-yen feedback loop could accelerate BoJ timeline",
      "supporting_sources": ["Morgan Stanley"],
      "consensus_level": "contrarian",
      "supporting_themes": ["BoJ surprise risk"],
      "supporting_trades": ["Short 10Y JGB futures, entry 144.50, target 142.00, stop 145.50"],
      "key_insight": "Morgan Stanley alone sees material risk of a Q1 BoJ policy shift, citing a feedback loop between stronger-than-expected wage growth and persistent yen weakness. This contrarian view is specific and actionable: 10Y JGB yields to 1.3% versus market pricing near 1.0%. For those running JGB duration, the MS short futures trade offers a hedge structure. Key catalyst to watch: Shunto wage negotiations in February."
    }
  ],
  "callouts": [
    {
      "text": "Morgan Stanley alone sees underpriced Q1 BoJ policy shift risk, projecting 10Y JGB yields at 1.3% versus Goldman's 1.1% cap, driven by strong wage data and yen weakness.",
      "source_through_line": "Goldman and JPMorgan expect gradual BoJ normalization, but Morgan Stanley sees underpriced Q1 policy shift risk"
    }
  ]
}
```

---

## Anti-Patterns: What to Avoid

### Anti-Pattern 1: Vague leads without specificity

**Bad:**
```json
{
  "lead": "Sources discuss Fed policy and its implications",
  "consensus_level": "moderate_consensus"
}
```

**Why it fails:** No directional call, no timing, no actionable takeaway. A trader reading this learns nothing.

**Better:**
```json
{
  "lead": "Three dealers converge on March Fed cut as employment data softens",
  "consensus_level": "strong_consensus"
}
```

---

### Anti-Pattern 2: Wrong consensus level assignment

**Bad (claiming strong_consensus with only 2 sources):**
```json
{
  "supporting_sources": ["Goldman Sachs", "JPMorgan"],
  "consensus_level": "strong_consensus"
}
```

**Why it fails:** `strong_consensus` requires 3+ sources. Two sources with no contradiction is `moderate_consensus`.

---

### Anti-Pattern 3: Missing attribution in key_insight

**Bad:**
```json
{
  "key_insight": "The Fed is likely to cut rates in March, with 75bp of easing expected by year-end. This reflects cooling labor market conditions and inflation normalization."
}
```

**Why it fails:** No sources cited. Reader cannot verify claims or assess credibility.

**Better:**
```json
{
  "key_insight": "Goldman Sachs, JPMorgan, and Barclays all project 75bp of Fed cuts in 2025 starting in Q1. The shared mechanism is labor market cooling and inflation normalization. Goldman's 5Y receiver trade offers a direct expression."
}
```

---

### Anti-Pattern 4: Treating topic overlap as consensus

**Bad:**
```json
{
  "lead": "Multiple sources discuss inflation dynamics",
  "consensus_level": "moderate_consensus",
  "supporting_sources": ["Goldman Sachs", "Barclays"]
}
```

**Why it fails:** Discussing the same topic is not consensus. Consensus requires directional alignment (e.g., both saying inflation will fall, or both saying it will rise).

---

### Anti-Pattern 5: Empty or irrelevant supporting_trades

**Bad:**
```json
{
  "supporting_themes": ["Fed pivot timing"],
  "supporting_trades": ["Short AAPL puts"],
  "key_insight": "The Fed is expected to cut rates..."
}
```

**Why it fails:** Trade is unrelated to the theme. Only include trades that logically express the through-line.

**Better:** Leave `supporting_trades` as an empty array `[]` if no relevant trades exist, or include only trades that directly relate to the insight.

---

## Checklist for Quality Through-Lines

Before finalizing output, verify each through-line meets these criteria:

- [ ] Lead is specific (includes direction, timing, or level)
- [ ] Consensus level follows rubric definitions exactly
- [ ] All claims in key_insight cite supporting sources
- [ ] Supporting_themes array matches actual theme labels from input
- [ ] Supporting_trades are logically related to the through-line
- [ ] Key_insight is under 120 words
- [ ] At least one through-line addresses divergence or risk if present in input
