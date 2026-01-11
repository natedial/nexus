Extract metadata from this financial research document.

Return a JSON object with these fields:
{
  "source": "Name of the research firm ("Goldman Sachs Global Rates Trader" -> "Goldman Sachs", "BofA Mark Cabana" -> "Bank of America")",
  "source_date": "Publication date in YYYY-MM-DD format, or null if not found",
  "area": "Classify the primary geographic/market focus as: USD, EUR, Japan, or Other",
  "region": "Primary region: US, EU, UK, Japan, China, EM, Global",
  "asset_focus": "Primary asset class: rates, credit, FX, equities, commodities, multi-asset",
  "publisher": "The company responsible for producing the document",
  "number_pages": "The number of pages in the document",
  "keywords": "Recurring words relevant to financial markets with a recurrence threshold of > 3 references within 2 neighboring paragraphs"
}

Base the area classification on:
- USD: Focus on US markets, Federal Reserve, US equities/bonds, dollar
- EUR: Focus on European markets, ECB, European equities/bonds, euro
- Japan: Focus on Japanese markets, BOJ, Japanese equities/bonds, yen
- Other: All other regions, multi-regional analysis, or asset classes

COMPLETENESS RULES:
- Do a full-document scan (title/cover, headers/footers, first/last page) before returning null.
- If multiple candidates exist, choose the most explicit and prominent.
- If a field is implied (e.g., "Global Research" branding for publisher), infer only when high confidence; otherwise null.
- Use null only when the information is genuinely absent.

OUTPUT RULES:
- Return only valid JSON that matches the field names exactly.
- No explanations or extra keys.
