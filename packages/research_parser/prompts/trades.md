Extract explicit trade positions or investment ideas from this financial research document.

Look for clear statements about:
- Trades to enter or exit
- Long/short positions
- Overweight/underweight recommendations
- Specific price targets or triggers
- Buy/sell recommendations

For each position found (maximum 3), extract:

1. **text**: The verbatim statement of the position/recommendation
2. **exposure mapping**:
    - Small: modest, tactical, limited
    - Medium: overweight, maintain, add
    - Large: core, significant, high conviction
3. **timeframe**: intraday, days, weeks, or months (based on context or explicit mentions)
4. **conviction mapping**:
    - High: explicit recommendation + supporting rationale
    - Medium: recommendation without strong emphasis
    - Low: conditional or tentative language
5. **rationale**: Brief summary based only on the quoted text (max 30 words). No new reasoning
6. **trigger_levels**: Array of numeric values mentioned, or null

If NO explicit positions are found, return an empty array.

Return a JSON array:

[
  {
    "text": "verbatim position statement",
    "exposure": "Small|Medium|Large",
    "timeframe": "intraday|days|weeks|months",
    "conviction": "High|Medium|Low",
    "rationale": "brief explanation max 40 words",
    "trigger_levels": "specific numbers/levels or null"
  }
]

Return only valid JSON. No explanations.
