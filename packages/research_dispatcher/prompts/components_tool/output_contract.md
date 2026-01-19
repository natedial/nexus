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
- strong_consensus: 3+ sources agree
- moderate_consensus: 2 sources agree, no contradictions
- mixed_views: sources present different angles on the same topic
- contrarian: single source with non-consensus view worth highlighting

OUTPUT RULES
1. Return EXACTLY ONE JSON object
2. 3-8 through-lines (prioritize quality over quantity)
3. Always attribute insights to sources
4. Highlight both consensus AND divergence
5. Connect trades to themes where logical relationships exist
6. 2-4 callouts (focus on highest-signal insights)
7. No commentary outside the JSON
