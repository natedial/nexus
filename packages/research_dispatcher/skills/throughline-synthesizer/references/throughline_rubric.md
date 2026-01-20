THROUGH-LINE SELECTION RUBRIC

## What is a Through-Line?
A through-line is a meta-narrative that emerges across multiple research documents. It synthesizes related themes and trades into a single actionable insight with clear source attribution.

---

## Selection Criteria

### Prioritize (in order):

1. **Cross-source consensus**
   - Multiple sources align on direction, risk, or trade expression
   - Stronger signal than any single source alone
   - Example: "GS, JPM, and Citi all favor front-end receivers ahead of Fed pivot"

2. **Cross-source divergence**
   - Sources disagree on the same topic
   - Signals uncertainty, asymmetric information, or bifurcated outcomes
   - Example: "Sources split on ECB: hawks see inflation persistence, doves cite growth drag"

3. **Actionable positioning**
   - Directly informs trade construction, hedging, or risk management
   - Includes specific instruments, levels, or timeframes
   - Example: "Multiple dealers recommend 2s10s steepeners as curve normalizes"

4. **Risk identification**
   - Surfaces threats to existing positions or consensus views
   - Highlights tail risks or underappreciated scenarios
   - Example: "Barclays and MS both flag Treasury supply as headwind for long-end"

5. **Novel contrarian view**
   - Non-consensus view from credible source
   - Must be specific and challenge a prevailing assumption
   - Example: "Deutsche alone sees risk of BoJ policy shift in Q1"

---

### Deprioritize:

- **Single-source without contrarian value**: One source saying something others don't mention (low signal)
- **Descriptive recaps**: Restating known events without forward implication
- **Vague or hedged**: "Markets are uncertain" or "It depends on data"
- **Off-topic**: Themes not relevant to rates, macro, or cross-market flows

---

## Through-Line Structure

Each through-line must include:

| Field | Description |
|-------|-------------|
| `lead` | One-line summary with causal or conditional relationship (max 25 words) |
| `supporting_sources` | Array of source names |
| `consensus_level` | See consensus_rubric.md for definitions |
| `supporting_themes` | Array of theme labels from input |
| `supporting_trades` | Array of trade descriptions (can be empty) |
| `key_insight` | Synthesis paragraph (max 120 words) covering agreement, disagreement, implications |

---

## Quality Checks

Before finalizing a through-line, verify:

1. **Attribution**: Every claim cites supporting sources
2. **Specificity**: Lead includes concrete detail (not generic statement)
3. **Actionability**: A trader reading this knows what to do or watch
4. **Consensus level accuracy**: Follows rules in consensus_rubric.md
5. **Non-redundancy**: Doesn't overlap significantly with another through-line

---

## Target Output

- Produce 3-8 through-lines per synthesis
- Prefer quality over quantity
- Cover both consensus AND divergence where present
- Include at least one risk-identifying through-line if material risks are present
