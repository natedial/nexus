"""Cross-document synthesis using LLM."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .llm import LLMClient, ModelConfig, load_model_config


# Load prompt from file
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "synthesis.md"


def _load_prompt() -> str:
    """Load synthesis prompt from markdown file."""
    return PROMPT_PATH.read_text().strip()


def _clean_json_response(text: str) -> str:
    """Clean JSON response from LLM (remove code fences, explanatory text, etc.)."""
    text = text.strip()

    # Find JSON object start
    json_start = -1
    for i, char in enumerate(text):
        if char == '{':
            json_start = i
            break

    if json_start > 0:
        text = text[json_start:]

    # Remove trailing code fences
    if "```" in text:
        text = text.split("```")[0]

    return text.strip()


@dataclass
class SynthesisResult:
    """Result of cross-document synthesis."""

    title: str
    document_count: int
    through_lines: list[dict]
    callouts: list[dict]
    raw_response: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for report."""
        return {
            "title": self.title,
            "document_count": self.document_count,
            "through_lines": self.through_lines,
            "callouts": self.callouts,
        }


class Synthesizer:
    """Performs cross-document synthesis using LLM."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
    ):
        self.client = LLMClient(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
        )
        self.config = load_model_config()
        self.prompt = _load_prompt()

    def synthesize(
        self,
        documents: list[dict[str, Any]],
    ) -> SynthesisResult | None:
        """
        Synthesize themes and trades across multiple documents.

        Args:
            documents: List of parsed_research records from Supabase

        Returns:
            SynthesisResult or None if synthesis fails
        """
        if not documents:
            print("No documents to synthesize")
            return None

        # Extract and format themes/trades from all documents
        input_data = self._prepare_input(documents)

        if not input_data["themes"]:
            print("No themes found in documents, skipping synthesis")
            return None

        print(f"Synthesizing {len(input_data['themes'])} themes and {len(input_data['trades'])} trades from {input_data['document_count']} documents...")

        # Call LLM
        raw_response = self.client.generate(
            config=self.config,
            system=self.prompt,
            user=json.dumps(input_data, indent=2),
        )

        # Parse response
        cleaned = _clean_json_response(raw_response)

        try:
            data = json.loads(cleaned)
            through_lines = data.get("through_lines", [])
            self._normalize_through_lines(through_lines)
            callouts = data.get("callouts", [])
            self._normalize_callouts(callouts, through_lines)
            result = SynthesisResult(
                title=data.get("title", "Cross-Document Synthesis"),
                document_count=data.get("document_count", len(documents)),
                through_lines=through_lines,
                callouts=callouts,
                raw_response=raw_response,
            )
            print(f"Synthesis complete: {result.title}")
            print(f"  Through-lines: {len(result.through_lines)}")
            print(f"  Callouts: {len(result.callouts)}")
            return result

        except (json.JSONDecodeError, ValueError) as e:
            print(f"Failed to parse synthesis JSON: {e}")
            print(f"Raw response (first 500 chars): {raw_response[:500]}")
            return None

    def _normalize_through_lines(self, through_lines: list[dict[str, Any]]) -> None:
        """Ensure through-lines have displayable source metadata."""
        for tl in through_lines:
            if not isinstance(tl, dict):
                continue
            if tl.get("source") or tl.get("document"):
                continue
            supporting_sources = tl.get("supporting_sources")
            if supporting_sources:
                tl["source"] = self._format_sources(supporting_sources)
                tl["document"] = "Cross-document synthesis"

    def _normalize_callouts(
        self,
        callouts: list[dict[str, Any]],
        through_lines: list[dict[str, Any]],
    ) -> None:
        """Ensure callouts have source attribution."""
        lead_to_sources = {}
        for tl in through_lines:
            if not isinstance(tl, dict):
                continue
            lead = tl.get("lead")
            sources = tl.get("supporting_sources")
            if lead and sources:
                lead_to_sources[lead] = sources

        for callout in callouts:
            if not isinstance(callout, dict):
                continue
            if callout.get("source"):
                continue
            lead = callout.get("source_through_line")
            sources = lead_to_sources.get(lead)
            if sources:
                callout["source"] = self._format_sources(sources)
            else:
                callout["source"] = "Multiple"

    def _format_sources(self, sources: list[str]) -> str:
        """Format source names into short, readable labels."""
        return ", ".join(self._abbreviate_source(name) for name in sources)

    def _abbreviate_source(self, name: str) -> str:
        """Create a short label for a source name (e.g., 'Goldman Sachs' -> 'GS')."""
        cleaned = " ".join(name.strip().split())
        if not cleaned:
            return "Unknown"
        overrides = {
            "Goldman Sachs": "GS",
            "JPMorgan": "JPM",
            "JP Morgan": "JPM",
            "JPMorgan Chase": "JPM",
            "JPMorgan Chase Research": "JPM",
            "Morgan Stanley": "MS",
            "Bank of America": "BofA",
            "Bank of America Merrill Lynch": "BofA",
            "Barclays": "Barcs",
            "Citigroup": "Citi",
            "Wells Fargo": "Wells",
            "Deutsche Bank": "DB",
            "BNP Paribas": "BNP",
            "UBS": "UBS",
            "HSBC": "HS",
            "Nomura": "Nomura",
            "Societe Generale": "SG",
            "Société Générale": "SG",
            "RBC Capital Markets": "RBC",
        }
        if cleaned in overrides:
            return overrides[cleaned]
        parts = cleaned.replace("&", " ").split()
        if len(parts) <= 1:
            return cleaned
        return "".join(part[0].upper() for part in parts if part)

    def _prepare_input(self, documents: list[dict[str, Any]]) -> dict:
        """
        Prepare input data for synthesis from raw documents.

        Extracts themes and trades, tags with source information.
        """
        themes = []
        trades = []
        sources = set()
        dates = []

        for doc in documents:
            parsed_data = doc.get("parsed_data", {})
            if not parsed_data:
                continue

            source = doc.get("source", "Unknown")
            doc_name = doc.get("document_name", "Unknown Document")
            source_date = doc.get("source_date")

            sources.add(source)
            if source_date:
                dates.append(source_date)

            # Extract themes with source attribution
            doc_themes = parsed_data.get("themes", [])
            if isinstance(doc_themes, list):
                for theme in doc_themes:
                    if isinstance(theme, dict):
                        themes.append({
                            "source": source,
                            "document": doc_name,
                            "label": theme.get("label", "Unlabeled"),
                            "context": theme.get("context", ""),
                            "strength": theme.get("strength", "Secondary"),
                            "confidence": theme.get("confidence", "Medium"),
                        })

            # Extract trades with source attribution
            doc_trades = parsed_data.get("trades", [])
            if isinstance(doc_trades, list):
                for trade in doc_trades:
                    if isinstance(trade, dict):
                        trades.append({
                            "source": source,
                            "document": doc_name,
                            "text": trade.get("text", ""),
                            "conviction": trade.get("conviction", "Medium"),
                            "timeframe": trade.get("timeframe", "weeks"),
                            "rationale": trade.get("rationale", ""),
                        })

        # Build date range string
        if dates:
            dates_sorted = sorted(dates)
            date_range = f"{dates_sorted[0]} to {dates_sorted[-1]}"
        else:
            date_range = datetime.now().strftime("%Y-%m-%d")

        return {
            "themes": themes,
            "trades": trades,
            "document_count": len(documents),
            "sources": list(sources),
            "date_range": date_range,
        }
