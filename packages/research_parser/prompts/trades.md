Extract explicit trade positions or investment ideas from this financial research document.

Look for clear statements about:
- Trades to enter or exit
- Long/short positions
- Overweight/underweight recommendations
- Specific price targets or triggers
- Buy/sell recommendations

For each position found (maximum 10), extract:

1. **text**: A concise, clinical rephrase of the position/recommendation. Do NOT include investment firm names. Do NOT use first-person (we/our/us/I). Use prescriptive phrasing (e.g., "Pay 5Y", "Maintain underweight in HY credit").
2. **exposure mapping**:
    - Small: modest, tactical, limited
    - Medium: overweight, maintain, add
    - Large: core, significant, high conviction
3. **timeframe**: intraday, days, weeks, or months (based on context or explicit mentions)
4. **conviction mapping**:
    - High: explicit recommendation + supporting rationale
    - Medium: recommendation without strong emphasis
    - Low: conditional or tentative language
5. **rationale**: Brief summary based only on the quoted text (max 50 words). No new reasoning. Avoid first-person voice.
6. **trigger_levels**: String of numeric levels mentioned (comma-separated), or null

If NO explicit positions are found, return an empty array.

Do NOT extract:
- Forecast changes with no position to enter, hold, close, buy, sell, pay, receive, overweight, underweight, hedge, or fade.
- Market views phrased only as expected central-bank timing, inflation paths, or yield targets.
- Duplicate restatements of the same trade; keep the clearest version with the most specific instrument and trigger levels.

Return a JSON array:

[
  {
    "text": "clinical, prescriptive trade statement without firm names or first-person voice",
    "exposure": "Small|Medium|Large",
    "timeframe": "intraday|days|weeks|months",
    "conviction": "High|Medium|Low",
    "rationale": "brief explanation max 50 words",
    "trigger_levels": "specific numbers/levels as a comma-separated string, or null"
  }
]

Return only valid JSON. No explanations.
