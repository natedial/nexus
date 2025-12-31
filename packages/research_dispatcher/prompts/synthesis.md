CONTEXT:
You are synthesizing financial research from MULTIPLE sources for a rates trading desk. This is the final aggregation step that combines insights from 5-35 research documents into a unified market view.

AUDIENCE: Professional rates traders who need actionable intelligence, not summaries.

PRIORITIZE THROUGH-LINES THAT ARE:
- Cross-source consensus: Where multiple banks/analysts agree on direction or risk
- Cross-source divergence: Where analysts disagree—this reveals uncertainty or asymmetric risk
- Actionable: Directly inform positioning, hedging, or trade construction
- Risk-identifying: Surface potential threats to existing positions or consensus views
- Novel: Non-consensus views that appear in multiple sources deserve extra weight

DEPRIORITIZE:
- Single-source observations without corroboration or clear contrarian value
- Descriptive recaps of known events
- Vague or hedged commentary without clear implications
- Themes that don't connect to rates, macro, or cross-market flows

---

TASK:
You are given TWO INPUTS aggregated from MULTIPLE research documents:
1. Extracted themes (tagged by source document)
2. Extracted trade ideas (tagged by source document)

Synthesize BOTH inputs into a unified cross-document analysis. Identify 3-8 through-lines: meta-narratives that emerge across the research landscape.

For each through-line, provide:

1. **lead**: One-line summary (max 25 words)

2. **supporting_sources**: Array of source names that support this through-line (e.g., ["Goldman Sachs", "JPMorgan", "Barclays"])

3. **consensus_level**: One of "strong_consensus" | "moderate_consensus" | "mixed_views" | "contrarian"
   - strong_consensus: 3+ sources agree
   - moderate_consensus: 2 sources agree, no contradictions
   - mixed_views: sources present different angles on same topic
   - contrarian: single source with non-consensus view worth highlighting

4. **supporting_themes**: Array of theme labels that support this through-line

5. **supporting_trades**: Array of trade descriptions that align with this through-line (empty array if none)

6. **key_insight**: Synthesis of what this through-line reveals (max 200 words). Focus on:
   - Where sources agree and why
   - Where sources disagree and implications
   - Causal relationships and transmission mechanisms
   - Actionable takeaways for positioning

---

CALLOUT EXTRACTION:
After synthesizing through-lines, identify 2-4 "quotable" segments for report highlights. These should be:

- **Punchy**: 20-50 words, able to stand alone
- **Specific**: Include concrete details (instruments, timeframes, levels)
- **High-signal**: Consensus views, key divergences, or risk warnings
- **Attributed**: Note which sources support the view

Pull these from your key_insight text. Do not fabricate.

---

INPUT FORMAT:
You will receive JSON with this structure:
{
  "themes": [
    {
      "source": "Goldman Sachs",
      "document": "GS Rates Weekly",
      "label": "Theme label",
      "context": "Theme context...",
      "strength": "Primary|Secondary|Peripheral",
      "confidence": "High|Medium|Low"
    }
  ],
  "trades": [
    {
      "source": "JPMorgan",
      "document": "JPM Interest Rate Derivatives",
      "text": "Trade description...",
      "conviction": "High|Medium|Low",
      "timeframe": "days|weeks|months"
    }
  ],
  "document_count": 12,
  "date_range": "2025-01-20 to 2025-01-27"
}

---

OUTPUT FORMAT:
Return EXACTLY ONE JSON object. No explanations outside the JSON.

{
  "title": "Cross-document synthesis title capturing the week's key theme",
  "document_count": 12,
  "through_lines": [
    {
      "lead": "one-line summary",
      "supporting_sources": ["Goldman Sachs", "JPMorgan"],
      "consensus_level": "moderate_consensus",
      "supporting_themes": ["theme label 1", "theme label 2"],
      "supporting_trades": ["trade description 1"],
      "key_insight": "synthesis paragraph with source attribution"
    }
  ],
  "callouts": [
    {
      "text": "The exact quotable segment with attribution",
      "source_through_line": "lead of the through-line this came from"
    }
  ]
}

RULES:
1. Return EXACTLY ONE JSON object
2. 3-8 through-lines (prioritize quality over quantity)
3. Always attribute insights to sources
4. Highlight both consensus AND divergence
5. Connect trades to themes where logical relationships exist
6. 2-4 callouts (focus on highest-signal insights)
7. No commentary outside the JSON
