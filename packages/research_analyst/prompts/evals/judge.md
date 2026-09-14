You are evaluating the output of an AI research analyst agent.

## Task
Score the agent's output against the source document and golden reference.
For Claim Grounding specifically, verify claims directly against the source document — not just the golden reference.

## Source Document
{{source_document}}

## Agent Output
{{agent_output}}

## Golden Reference
{{golden_output}}

## Scoring Rubric (score 0-1 each)

1. **Thesis Clarity** (0-1): Does the thesis capture the document's core argument? Is it specific, actionable, and grounded in the source content?
2. **Claim Grounding** (0-1): Are claims traceable to the source document? Penalise claims that cannot be verified in the source text, even if they match the golden reference.
3. **Trading Actionability** (0-1): Are opportunities specific and executable? Do they include instrument, direction, timeframe, and rationale?
4. **Talking Point Quality** (0-1): Are insights quotable and presentation-ready? Do they provide clear context?
5. **Coherence** (0-1): Do thesis, positioning, and contrarian views align logically? Are there contradictions?

## Output Format
Return JSON:
{
  "scores": {
    "thesis_clarity": 0.0,
    "claim_grounding": 0.0,
    "trading_actionability": 0.0,
    "talking_point_quality": 0.0,
    "coherence": 0.0
  },
  "reasoning": "Brief explanation of scores",
  "errors": ["List of issues found"]
}

## Guidelines
- Scores should reflect the quality of the agent's output relative to what a human analyst would produce
- A score of 1.0 means the output matches or exceeds the golden reference
- A score of 0.5 means the output is adequate but not as good as the reference
- A score of 0.0 means the output is missing, wrong, or fundamentally flawed
- If any required field is missing entirely, score that dimension at 0.0
- For Claim Grounding: a claim present in the golden reference but absent from the source document should still be penalised
