You are analyzing a financial research document to extract themes with high coverage and evidence.

  GOAL
  - Identify themes so that the overwhelming majority of content paragraphs can be cleanly tied to at least one theme.

  PROCESS (3 passes, conditional extensions, max 6 iterations total)
  PASS 1 (High recall): List candidate themes with broad coverage. Do not merge yet.
  PASS 2 (Merge & refine): Merge conceptually identical themes; tighten labels and scope; add evidence anchors.
  PASS 3 (Coverage audit): Compute coverage metrics and verify gating criteria.
  If any gate fails, iterate: add/adjust themes and re‑audit.

  EXTENSION RULE
  - If gates fail after pass 4, allow up to 2 additional passes (max 6) ONLY if coverage_ratio is strictly increasing
  OR new themes are added.
  - If gates still fail after pass 6, hard stop and return JSON with failed_gates populated and a brief audit note
  explaining why.

  OUTPUT MUST ALWAYS DISCLOSE FAILURE
  - failed_gates MUST be non‑empty if any gate remains unsatisfied at termination.

  THEME MERGING
  Combine conceptually identical themes even if phrased differently (e.g., "Fed rate path" and "FOMC policy
  trajectory" = one theme).

  DEFINITIONS
  - Paragraph = a block separated by blank lines in the document.
  - Covered paragraph = can be linked to at least one theme with an excerpt from that paragraph or a paragraph_anchor.
  - Excluded paragraph = non‑content (headers, boilerplate, legal, footers). Exclusions must be listed.

  GATING CRITERIA (must pass)
  1) Coverage: covered_paragraphs / (total_paragraphs - excluded_paragraphs) >= 0.80
  2) No orphan sections: sections_with_zero_themes == 0 (if section headers exist)
  3) Evidence density: every Primary theme has evidence_count >= 2 (distinct paragraphs)
  4) Stability: final pass introduces no new themes
  5) Analytical depth: at least 60% of Primary themes must show at least one of: a transmission mechanism (how X affects Y), a conditional forecast with triggers, or a cross-asset/policy implication explicitly tied to the thesis.

  OUTPUT FORMAT (valid JSON only, no explanations)
  {
    "coverage": {
      "total_paragraphs": number,
      "excluded_paragraphs": number,
      "covered_paragraphs": number,
      "coverage_ratio": number,
      "sections_with_zero_themes": number,
      "excluded_paragraphs_notes": ["short reason per exclusion"],
      "failed_gates": ["if any failed at termination, list here; otherwise []"],
      "audit_notes": "short reason for unresolved gates, if any"
    },
    "themes": [
      {
        "label": "concise 3-6 word label",
        "scope": "Macro|Sector|Asset|Company|Policy|Positioning|Flows|Technical|Risk|Other",
        "section_anchor": "section title or first 5-8 words of a representative paragraph",
        "excerpts": [
          {"text": "verbatim quote from paragraph A (80-100 words max, prefer complete analytical claim with reasoning, not topic fragment)"},
          {"text": "verbatim quote from paragraph B (80-100 words max, prefer complete analytical claim with reasoning, not topic fragment)"}
        ],
        "relevance": ["Macro|Rates|Credit|Equities|FX|Commodities|Geopolitics|Sentiment|Flows|Technical"],
        "primary_category": "single category from relevance",
        "classification": "Opinion|Forecast|Description",
        "evidence_count": number,
        "strength": "Primary|Secondary|Peripheral",
        "directionality": {"tag": count} or null,
        "confidence": "High|Medium|Low",
        "context": "3-5 sentences capturing: 1) THESIS: the core analytical claim or primary driver, 2) TRANSMISSION: how this propagates through markets/sectors/economy, 3) IMPLICATIONS: specific policy/positioning/risk/market consequences. Example GOOD: 'Energy supply shock is identified as near-term driver for cost-push inflation. Energy costs form first wave, but downstream impacts in fertilizer, chemicals, medicines, plastics, manufacturing inputs see passthroughs. Longer-lasting and complex for central banks to interpret cleanly, increasing odds of hawkish pauses.' Example BAD: 'Energy prices are rising due to geopolitical risk.'"
      }
    ],
    "excluded_topics": ["brief topics mentioned but excluded, if any"]
  }

  RULES
  - Return 6–12 themes for typical docs; for long docs, allow up to 16 if needed to satisfy coverage gates.
  - Excerpts must be EXACT text from the document—no paraphrasing.
  - Each Primary theme must include 2 excerpts from distinct paragraphs.
  - Secondary themes require at least 1 excerpt; 2 if available.
  - If relevance includes Rates/Equities/FX/Credit/Commodities and tone is present, directionality must be non‑null;
  otherwise null.
  - mention_count is removed; use evidence_count (distinct paragraphs).
  - At least 50% of Primary themes must include at least one excerpt containing: a conditional forecast, or a causal mechanism, or a cross-asset/market implication.
  - Return only valid JSON and nothing else.
