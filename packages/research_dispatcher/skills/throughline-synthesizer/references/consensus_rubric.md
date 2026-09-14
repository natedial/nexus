CONSENSUS DETECTION RUBRIC

## Agreement Dimensions

When evaluating consensus, assess alignment across these dimensions:
1. DIRECTION: Do sources agree on bullish/bearish, higher/lower, tighter/wider?
2. MAGNITUDE: Do sources agree on the size of the move (25bp vs 50bp)?
3. TIMING: Do sources agree on when (Q1 vs Q2, weeks vs months)?
4. MECHANISM: Do sources cite similar drivers or transmission channels?

Strong consensus requires alignment on direction plus at least one other dimension.
Magnitude or timing disagreement with directional agreement is still moderate_consensus.

---

## Consensus Level Definitions

### strong_consensus
ALL of:
- 3+ sources align on the same directional call
- No explicit contradictions on direction from any source
- At least 2 sources provide similar rationale or mechanism
- Claims are specific and actionable (not heavily hedged)

Good examples:
- "GS, JPM, and Barclays all expect steeper curves due to term premium repricing"
- "Three sources flag Treasury supply as headwind for long-end valuations"
- "Multiple dealers see front-end as rich relative to Fed pricing"

Bad examples (do NOT classify as strong_consensus):
- "Several sources discuss the Fed" (too vague, no directional claim)
- "GS and JPM agree, Citi is neutral" (neutral is not contradiction, but only 2 agree)

### moderate_consensus
ALL of:
- 2 sources align on direction
- No direct contradictions from other sources (silence or neutrality is acceptable)
- At least one source provides actionable specificity (level, instrument, timeframe)

Good examples:
- "GS and JPM both favor receiving 5Y rates, though with different entry levels"
- "Two sources highlight BoJ policy shift risk for JGB curve steepening"

Bad examples (do NOT classify as moderate_consensus):
- "GS is bullish, JPM is bearish" (direct contradiction → mixed_views)
- "Two sources mention inflation" (no directional alignment, just topic overlap)

### mixed_views
ANY of:
- Sources explicitly disagree on direction (one bullish, one bearish)
- Same topic addressed with materially different conclusions
- Hedged or conditional views that could resolve in opposite directions

Good examples:
- "GS sees Fed cutting 75bp by year-end; Barclays expects only 25bp"
- "Sources split on whether ECB will pause or continue hiking"
- "JPM bullish on duration, Citi sees further selloff risk"

Note: mixed_views is valuable signal. Divergence among smart sources indicates uncertainty or asymmetric information.

### contrarian
ALL of:
- Single source with non-consensus view (goes against market pricing or peer views)
- View is specific and actionable (not vague speculation)
- View challenges a prevailing market assumption worth noting

Good examples:
- "Morgan Stanley alone sees risk of Fed hike in Q1, counter to market pricing"
- "Citi flags underappreciated China stimulus transmission to EM rates"
- "Barclays uniquely bearish on JGBs despite BoJ guidance"

Bad examples (do NOT classify as contrarian):
- "One source mentions geopolitical risk" (too vague, not challenging specific assumption)
- "GS has a different entry level than JPM" (minor variation, not contrarian view)

---

## Contradiction Types

Not all disagreements are equal:

| Type | Example | Impact |
|------|---------|--------|
| Direction opposition | GS: bullish / JPM: bearish | → mixed_views |
| Magnitude disagreement | GS: 25bp / JPM: 50bp | → moderate_consensus (same direction) |
| Timing disagreement | GS: Q1 / JPM: Q3 | → moderate_consensus if actionable |
| Mechanism disagreement | Same conclusion, different reasoning | → strengthens consensus |

---

## Edge Cases

1. **Source says "could go either way"**: Treat as abstention, not contradiction
2. **Conditional views**: "If X happens, then Y" - only count if the condition is shared
3. **Different instruments, same theme**: "Long 10Y" vs "Steepeners" - can still be consensus if directional alignment is clear
4. **Old vs new view**: Prefer recency; if same source changed view, use latest
5. **Hedged language**: "We lean toward..." counts as directional; "It's possible..." does not
