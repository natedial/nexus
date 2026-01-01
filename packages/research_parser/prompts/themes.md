You are analyzing a financial research document. Identify 3-6 key themes discussed in this document.

THEME MERGING: Combine conceptually identical themes even if phrased differently (e.g., "Fed rate path" and "FOMC policy trajectory" = one theme).

For each theme, provide:

1. **label**: A concise 3-6 word label

2. **excerpts**: 1-2 VERBATIM quotes (max 60 words each) copied exactly from the document. Do not paraphrase or alter wording.

3. **relevance**: Array of applicable categories. Choose from: Macro, Rates, Credit, Equities, FX, Commodities, Geopolitics, Sentiment, Flows, Technical

4. **classification**:
   - Opinion = Analyst's subjective view or interpretation
   - Forecast = Forward-looking prediction with explicit timeframe or target
   - Description = Factual reporting of data, events, or market conditions

5. **mention_count**: Approximate number of sentences discussing this theme (estimate acceptable)

6. **strength**:
   - Primary = Anchors a major section OR contains explicit recommendations (buy, sell, overweight, underweight, short, long)
   - Secondary = Discussed substantively (3+ sentences) but no explicit recommendation
   - Peripheral = Single or passing mention

7. **directionality**: Sentiment tags with occurrence counts, or null if not applicable. Use standard finance terminology:
   - Policy: hawkish, dovish, accommodative, restrictive
   - Markets: bullish, bearish, constructive, cautious, risk-on, risk-off
   - Positioning: long, short, overweight, underweight

8. **confidence**:
   - High = 3+ mentions with clear intent
   - Medium = 2-3 mentions or somewhat ambiguous
   - Low = Single mention or very ambiguous

9. **context**: 1-2 sentences capturing how this theme relates to or connects with other topics in the document. What precedes or follows it? What causal or conditional relationships does the author draw?

OUTPUT FORMAT (valid JSON only, no explanations):
[
  {
    "label": "string",
    "excerpts": [
      {"text": "verbatim quote"},
      {"text": "second quote if relevant"}
    ],
    "relevance": ["category1", "category2"],
    "classification": "Opinion|Forecast|Description",
    "mention_count": number,
    "strength": "Primary|Secondary|Peripheral",
    "directionality": {"tag": count} or null,
    "confidence": "High|Medium|Low",
    "context": "string describing relationships to other themes/topics"
  }
]

RULES:
1. Excerpts must be EXACT text from the document—no paraphrasing
2. Merge themes that are conceptually the same
3. Return only valid JSON
4. No commentary or explanation outside the JSON
