# Callout Extractor: Few-Shot Examples

This document provides complete input/output examples demonstrating proper callout extraction from synthesized through-lines, following the selection priority order and quality criteria.

---

## Example 1: Strong Consensus with Trade Implication (Priority 1)

### Input (Through-Lines from Stage 1)

```json
{
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
  ]
}
```

### Output

```json
{
  "callouts": [
    {
      "text": "Goldman Sachs, JPMorgan, and Barclays all project 75bp of Fed cuts in 2025 starting in Q1, with labor market cooling as the shared catalyst. Goldman's 5Y receiver at 3.85% offers a direct expression with defined stops.",
      "source_through_line": "Three major dealers converge on March Fed cut as employment data softens and inflation normalizes"
    },
    {
      "text": "Morgan Stanley and JPMorgan favor 2s10s steepeners, with MS targeting 50-75bp of normalization as front-end rates reprice faster than the long end. JPM entry at -25bp provides specific execution.",
      "source_through_line": "Curve steepening trades gain support as Fed pivot reprices the front end faster than the long end"
    }
  ]
}
```

### Why These Callouts Work

1. **First callout (Priority 1 - Strong consensus with trade):**
   - Names all three sources explicitly
   - Quantifies the consensus (75bp, Q1, March)
   - States the shared mechanism (labor market cooling)
   - Includes the actionable trade with level (5Y at 3.85%)
   - 43 words, punchy and standalone

2. **Second callout (Priority 1 - Moderate consensus with trade):**
   - Names both sources
   - Quantifies the expected move (50-75bp)
   - States the mechanism (front-end more sensitive)
   - Includes execution level (-25bp entry)
   - 36 words, actionable

---

## Example 2: Key Divergence Worth Watching (Priority 2)

### Input (Through-Lines from Stage 1)

```json
{
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
  ]
}
```

### Output

```json
{
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

### Why These Callouts Work

1. **First callout (Priority 2 - Key divergence):**
   - Contrasts two specific views with numbers (100bp vs 50bp, April vs June)
   - Names both sources with their positions
   - States the implication (two-way risk around meetings)
   - 32 words, captures the material disagreement

2. **Second callout (Priority 3/4 - Risk warning + contrarian):**
   - Single source with non-consensus view
   - Specific risk identified (Q2 supply overwhelming ECB cuts)
   - Includes actionable trade (10s30s at 35bp)
   - 29 words, flags underappreciated risk

---

## Example 3: Risk Warning and Contrarian View (Priority 3-4)

### Input (Through-Lines from Stage 1)

```json
{
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
      "lead": "Treasury supply surge in Q2 refunding could challenge long-end valuations despite Fed easing",
      "supporting_sources": ["Barclays", "Morgan Stanley"],
      "consensus_level": "moderate_consensus",
      "supporting_themes": ["Treasury issuance dynamics", "Long-end supply pressure"],
      "supporting_trades": [],
      "key_insight": "Barclays and Morgan Stanley both flag Treasury supply as a headwind for long-end duration. The Q2 refunding is expected to bring elevated coupon issuance, which may steepen the curve even if the Fed cuts. This creates a disconnect: front-end rallies on Fed easing while the long end struggles with supply absorption. Neither source has an explicit trade, but the implication is to favor curve steepeners over outright longs."
    }
  ]
}
```

### Output

```json
{
  "callouts": [
    {
      "text": "Morgan Stanley alone sees underpriced Q1 BoJ policy shift risk, projecting 10Y JGB yields at 1.3% by March versus Goldman's 1.1% cap. MS short futures at 144.50 offers a hedge for JGB duration.",
      "source_through_line": "Goldman and JPMorgan expect gradual BoJ normalization, but Morgan Stanley sees underpriced Q1 policy shift risk"
    },
    {
      "text": "Barclays and Morgan Stanley flag Q2 Treasury refunding as a headwind for long-end duration, suggesting curve steepeners over outright longs even as the Fed cuts.",
      "source_through_line": "Treasury supply surge in Q2 refunding could challenge long-end valuations despite Fed easing"
    }
  ]
}
```

### Why These Callouts Work

1. **First callout (Priority 4 - Novel contrarian view):**
   - Single source challenging consensus with specific numbers (1.3% vs 1.1%)
   - Includes timing (Q1, March)
   - Provides actionable hedge (short futures at 144.50)
   - 39 words, specific and standalone

2. **Second callout (Priority 3 - Risk warning):**
   - Two credible sources identifying same risk
   - Specific catalyst (Q2 refunding)
   - Actionable implication (steepeners over outright longs)
   - 30 words, even without explicit trade level

---

## Selection Priority Decision Tree

When multiple through-lines compete for callout selection, use this priority order:

```
1. Strong consensus + trade implication?
   └─ YES → Extract first
   └─ NO → Continue

2. Material divergence between smart sources?
   └─ YES → Extract (quantify the gap)
   └─ NO → Continue

3. Risk warning from credible source(s)?
   └─ YES → Extract (especially if underappreciated)
   └─ NO → Continue

4. Novel contrarian view with specificity?
   └─ YES → Extract (name the source, quantify the call)
   └─ NO → Skip (likely not callout-worthy)
```

---

## Anti-Patterns: What to Avoid

### Anti-Pattern 1: Vague statements without specifics

**Bad:**
```json
{
  "text": "Sources see the Fed cutting rates this year, which could impact markets.",
  "source_through_line": "Fed policy outlook"
}
```

**Why it fails:** No numbers, no timing, no sources named, no actionable takeaway. "Could impact markets" adds nothing.

**Better:**
```json
{
  "text": "Goldman, JPMorgan, and Barclays all project 75bp of Fed cuts starting March 2025, with Goldman's 5Y receiver at 3.85% as the direct trade expression.",
  "source_through_line": "Three major dealers converge on March Fed cut"
}
```

---

### Anti-Pattern 2: Missing source attribution

**Bad:**
```json
{
  "text": "The ECB is likely to cut rates by 75bp this year, starting in April, as growth weakness dominates inflation concerns.",
  "source_through_line": "ECB cutting cycle"
}
```

**Why it fails:** No sources named. Reader cannot assess credibility or verify the claim.

**Better:**
```json
{
  "text": "Citi and Deutsche Bank expect 75-100bp of ECB cuts starting April, driven by German recession risk and growth weakness dominating inflation concerns.",
  "source_through_line": "ECB cutting cycle"
}
```

---

### Anti-Pattern 3: Recapping known events

**Bad:**
```json
{
  "text": "The Fed held rates steady at its January meeting, as widely expected by markets.",
  "source_through_line": "Fed policy update"
}
```

**Why it fails:** This is a backward-looking recap with no forward implication. Callouts must be forward-looking and actionable.

---

### Anti-Pattern 4: Fabricating details not in the synthesis

**Bad (inventing a level not in the through-line):**
```json
{
  "text": "Goldman sees 10Y Treasury yields falling to 3.25% by June as the Fed cuts.",
  "source_through_line": "Fed pivot consensus"
}
```

**Why it fails:** If the through-line's key_insight did not mention "3.25%" or "June", this is fabrication. Callouts must pull directly from synthesized content.

---

### Anti-Pattern 5: Exceeding word limit or being too dense

**Bad (68 words, too long):**
```json
{
  "text": "Goldman Sachs, JPMorgan, and Barclays all expect the Fed to begin cutting rates in March 2025, with a total of 75 basis points of easing by year-end. The primary driver is the cooling labor market, which has become the binding constraint on policy. Goldman recommends receiving 5Y SOFR at 3.85% with a target of 3.50% and a stop at 4.05%.",
  "source_through_line": "Fed pivot consensus"
}
```

**Why it fails:** Over 50 words, too much detail. Callouts should be 20-50 words.

**Better (43 words):**
```json
{
  "text": "Goldman Sachs, JPMorgan, and Barclays all project 75bp of Fed cuts in 2025 starting in Q1, with labor market cooling as the shared catalyst. Goldman's 5Y receiver at 3.85% offers a direct expression with defined stops.",
  "source_through_line": "Fed pivot consensus"
}
```

---

## Quality Checklist for Callouts

Before finalizing callout extraction, verify each callout meets these criteria:

- [ ] **Punchy**: 20-50 words, standalone without additional context
- [ ] **Specific**: Includes at least one of: instrument, curve point, level, or timeframe
- [ ] **Attributed**: Names the supporting sources explicitly
- [ ] **Grounded**: Every claim appears in the source through-line's key_insight
- [ ] **Actionable**: Reader knows what to do or watch after reading
- [ ] **Priority-aligned**: Higher-priority callouts are included before lower-priority ones
- [ ] **Non-redundant**: Each callout covers distinct information

---

## Mapping Through-Lines to Callout Priority

| Through-Line Characteristics | Callout Priority | Extract? |
|------------------------------|------------------|----------|
| `strong_consensus` + trade in `supporting_trades` | 1 (highest) | Yes |
| `moderate_consensus` + specific trade | 1-2 | Yes |
| `mixed_views` with quantified divergence | 2 | Yes |
| `moderate_consensus` + risk flag | 3 | Yes |
| `contrarian` with specific call | 4 | Yes |
| `moderate_consensus` without trade or risk | Low | Maybe |
| Vague or descriptive through-line | N/A | No |

Target: 2-4 callouts per synthesis. Quality over quantity.
