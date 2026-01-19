INPUT FORMAT
You will receive JSON with this structure:
{
  "themes": [
    {
      "source": "Goldman Sachs",
      "document": "GS Rates Weekly",
      "label": "Theme label",
      "context": "Theme context...",
      "strength": "Primary|Secondary|Peripheral",
      "confidence": "High|Medium|Low"
    }
  ],
  "trades": [
    {
      "source": "JPMorgan",
      "document": "JPM Interest Rate Derivatives",
      "text": "Trade description...",
      "conviction": "High|Medium|Low",
      "timeframe": "days|weeks|months"
    }
  ],
  "document_count": 12,
  "date_range": "2025-01-20 to 2025-01-27"
}
