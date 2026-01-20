CALLOUT EXTRACTION RUBRIC

## Purpose
Callouts are quotable highlights for the report. They should be the highest-signal sentences from the synthesis that a trader could scan in 10 seconds and immediately understand the key takeaway.

## Quality Criteria

### Required (ALL must be met):
1. **Punchy**: 20-50 words, able to stand alone without context
2. **Specific**: Include at least one of: instrument, curve point, level, or timeframe
3. **Attributed**: Name the supporting sources (e.g., "GS and JPM both see...")
4. **Grounded**: Pull directly from synthesized key_insight text; never fabricate

### Preferred (aim for most):
5. **Actionable**: Implies a positioning decision or monitoring priority
6. **Quantified**: Includes numbers where available (bp, %, dates)
7. **Causal**: States a "because" or "if-then" relationship

---

## Selection Priority

Extract callouts in this priority order:

1. **Strong consensus with trade implication**
   - Multiple sources agree AND there's a clear positioning takeaway
   - Example: "GS, JPM, and Barclays all favor receiving 5Y, citing term premium compression as the Fed pivots"

2. **Key divergence worth watching**
   - Smart sources disagree on something material
   - Example: "Sources split on ECB timing: Citi sees June cut, Barclays expects September"

3. **Risk warning from credible source**
   - Identifies threat to consensus or existing positions
   - Example: "Morgan Stanley flags underappreciated risk of Treasury supply disruption in Q2 refunding"

4. **Novel contrarian view**
   - Single source challenging market assumption with specificity
   - Example: "Deutsche uniquely bearish on JGBs, expecting 10Y to test 1.5% despite BoJ guidance"

---

## What NOT to Extract

- Vague statements without specifics ("Markets remain uncertain")
- Recaps of known events ("The Fed held rates steady")
- Hedged views without conviction ("It's possible rates could move")
- Themes without actionable implication ("Inflation remains a topic")

---

## Output Format

Each callout must include:
- `text`: The quotable segment (20-50 words)
- `source_through_line`: The lead of the through-line this came from

Extract 2-4 callouts total. Prefer quality over quantity.
