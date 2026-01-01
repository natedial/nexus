Extract explicit trade positions or investment ideas from this financial research document.

Look for clear statements about:
- Trades to enter or exit
- Long/short positions
- Overweight/underweight recommendations
- Specific price targets or triggers
- Buy/sell recommendations

For each position found (maximum 3), extract:

1. **text**: The verbatim statement of the position/recommendation
2. **exposure**: Small, Medium, or Large (based on language like "modest", "significant", "core position")
3. **timeframe**: intraday, days, weeks, or months (based on context or explicit mentions)
4. **conviction**: High, Medium, or Low (based on language strength and supporting evidence)
5. **rationale**: A brief summary (max 40 words) of why this position is recommended
6. **trigger_levels**: Any specific numeric levels mentioned (prices, yields, etc.) or null

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
