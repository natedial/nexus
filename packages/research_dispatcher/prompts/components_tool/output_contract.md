OUTPUT FORMAT
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

CONSENSUS LEVELS

strong_consensus
Requirements (ALL must be met):
- 3+ sources align on the same directional call
- No explicit contradictions on direction
- At least 2 sources provide similar rationale or mechanism
- Claims are specific (not heavily hedged)

moderate_consensus
Requirements (ALL must be met):
- 2 sources align on direction
- No direct contradictions from other sources
- At least one source provides actionable specificity

mixed_views
Requirements (ANY of these):
- Sources explicitly disagree on direction
- Same topic addressed with materially different conclusions
- Hedged or conditional views that could resolve either way

contrarian
Requirements (ALL must be met):
- Single source with non-consensus view
- View is specific and actionable (not vague speculation)
- View challenges a prevailing market assumption

OUTPUT RULES
1. Return EXACTLY ONE JSON object
2. 3-8 through-lines (prioritize quality over quantity)
3. Always attribute insights to sources
4. Highlight both consensus AND divergence
5. Connect trades to themes where logical relationships exist
6. 2-4 callouts (focus on highest-signal insights)
7. No commentary outside the JSON
