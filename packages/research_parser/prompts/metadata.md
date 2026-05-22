You are extracting metadata from a financial research document.  
Use only information present in the document text (including headers/footers, title page, and disclaimers).

Return ONLY valid JSON with this exact schema and field order:

{
  "source": string|null,
  "source_date": string|null,
  "area": "USD"|"EUR"|"Japan"|"Other",
  "region": "US"|"EU"|"UK"|"Japan"|"China"|"EM"|"Global"|null,
  "asset_focus": "rates"|"credit"|"FX"|"equities"|"commodities"|"multi-asset"|null,
  "publisher": string|null,
  "number_pages": integer|null,
  "keywords": string[]
}

Rules:

1) source
- Extract the research brand/team/author source and normalize:
  - "Goldman Sachs Global Rates Trader" -> "Goldman Sachs"
  - "BofA Mark Cabana" -> "Bank of America"
- Prefer canonical institution name.
- If not found, return null.

2) source_date
- Extract publication date.
- Convert to YYYY-MM-DD.
- If ambiguous or missing, return null.

3) area
- Choose one:
  - USD: US markets, Federal Reserve, Treasuries, USD
  - EUR: Euro area/ECB/euro rates or bonds
  - Japan: BOJ/JGB/yen/Japan markets
  - Other: everything else, mixed focus, or unclear
- Must always return one of the 4 values.

4) region
- Primary region only: US, EU, UK, Japan, China, EM, Global.
- Use Global for clearly multi-region content.
- If unknown, null.

5) asset_focus
- Primary asset class: rates, credit, FX, equities, commodities, multi-asset.
- If multiple with no clear primary, use multi-asset.
- If unknown, null.

6) publisher
- Company responsible for producing the document (from masthead/disclaimer/copyright).
- If missing, set publisher = source when source is an institution.
- Else null.

7) number_pages
- Total page count as integer.
- If unavailable, null.

8) keywords (IMPORTANT: do not return null)
- Return an array of recurring market-relevant terms (lowercase).
- Include single terms or short phrases (1-3 words), e.g. "treasury yields", "curve steepening", "core pce", "credit spreads".
- Primary rule: include terms with frequency >= 3 across the document and appearing in at least 2 nearby paragraph windows.
- Normalize variants (e.g., "Treasury"/"Treasuries" -> "treasury"; "Fed"/"Federal Reserve" -> "federal reserve").
- Exclude generic words: "market", "report", "chart", "figure", "table", "source", month names, and boilerplate disclaimer text.
- Backoff rule: if nothing meets primary rule, return top 3-8 salient finance terms with frequency >= 2.
- Only return [] if the document has insufficient readable text to extract terms.

Output constraints:
- Return JSON only. No markdown, no comments, no explanation.
- Use null only where allowed above.

