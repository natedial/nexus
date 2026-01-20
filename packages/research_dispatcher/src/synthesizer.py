"""Cross-document synthesis using LLM with optional skill-based pipeline."""

import json
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any

from .llm import LLMClient, ModelConfig, load_model_config, load_skill_config


# Prompt paths
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "synthesis.md"
SKILL_PROMPTS_PATH = Path(__file__).parent.parent / "prompts" / "skills"


def _load_prompt(filename: str = "synthesis.md") -> str:
    """Load prompt from markdown file."""
    if filename == "synthesis.md":
        return PROMPT_PATH.read_text().strip()
    return (SKILL_PROMPTS_PATH / filename).read_text().strip()


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
        use_skill_pipeline: bool = False,
    ):
        self.client = LLMClient(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
        )
        self.use_skill_pipeline = use_skill_pipeline

        # Load monolithic config/prompt
        self.config = load_model_config()
        self.prompt = _load_prompt()

        # Skill configs (lazy-loaded)
        self._throughline_config: ModelConfig | None = None
        self._callout_config: ModelConfig | None = None
        self._throughline_prompt: str | None = None
        self._callout_prompt: str | None = None

    @property
    def throughline_config(self) -> ModelConfig:
        """Lazy-load throughline synthesizer config."""
        if self._throughline_config is None:
            self._throughline_config = load_skill_config("throughline_synthesizer")
        return self._throughline_config

    @property
    def callout_config(self) -> ModelConfig:
        """Lazy-load callout extractor config."""
        if self._callout_config is None:
            self._callout_config = load_skill_config("callout_extractor")
        return self._callout_config

    @property
    def throughline_prompt(self) -> str:
        """Lazy-load throughline synthesizer prompt."""
        if self._throughline_prompt is None:
            self._throughline_prompt = _load_prompt("throughline_synthesizer.md")
        return self._throughline_prompt

    @property
    def callout_prompt(self) -> str:
        """Lazy-load callout extractor prompt."""
        if self._callout_prompt is None:
            self._callout_prompt = _load_prompt("callout_extractor.md")
        return self._callout_prompt

    def synthesize(
        self,
        documents: list[dict[str, Any]],
    ) -> SynthesisResult | None:
        """
        Synthesize themes and trades across multiple documents.

        Uses skill pipeline if enabled, otherwise falls back to monolithic prompt.

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

        if self.use_skill_pipeline:
            return self._synthesize_with_skills(input_data, len(documents))
        else:
            return self._synthesize_monolithic(input_data, len(documents))

    def _synthesize_monolithic(
        self,
        input_data: dict,
        document_count: int,
    ) -> SynthesisResult | None:
        """Original monolithic synthesis using single LLM call."""
        raw_response = self.client.generate(
            config=self.config,
            system=self.prompt,
            user=json.dumps(input_data, indent=2),
        )

        cleaned = _clean_json_response(raw_response)

        try:
            data = json.loads(cleaned)
            through_lines = data.get("through_lines", [])
            self._normalize_through_lines(through_lines)
            callouts = data.get("callouts", [])
            self._normalize_callouts(callouts, through_lines)
            result = SynthesisResult(
                title=data.get("title", "Cross-Document Synthesis"),
                document_count=data.get("document_count", document_count),
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

    def _synthesize_with_skills(
        self,
        input_data: dict,
        document_count: int,
    ) -> SynthesisResult | None:
        """Two-stage synthesis using skills."""
        print("  Using skill-based pipeline...")

        # Stage 1: Extract through-lines
        print("  Stage 1: Extracting through-lines...")
        stage1_result = self._stage1_throughlines(input_data)

        if stage1_result is None:
            print("  Stage 1 failed, aborting synthesis")
            return None

        title = stage1_result.get("title", "Cross-Document Synthesis")
        through_lines = stage1_result.get("through_lines", [])

        if not through_lines:
            print("  Stage 1 returned no through-lines")
            return None

        print(f"  Stage 1 complete: {len(through_lines)} through-lines")

        # Stage 2: Extract callouts
        print("  Stage 2: Extracting callouts...")
        callouts = self._stage2_callouts(through_lines)

        if callouts is None:
            print("  Stage 2 failed, returning through-lines without callouts")
            callouts = []
        else:
            print(f"  Stage 2 complete: {len(callouts)} callouts")

        # Post-process
        self._normalize_through_lines(through_lines)
        self._normalize_callouts(callouts, through_lines)

        result = SynthesisResult(
            title=title,
            document_count=document_count,
            through_lines=through_lines,
            callouts=callouts,
            raw_response=None,
        )
        print(f"Synthesis complete: {result.title}")
        print(f"  Through-lines: {len(result.through_lines)}")
        print(f"  Callouts: {len(result.callouts)}")
        return result

    def _stage1_throughlines(self, input_data: dict) -> dict | None:
        """Stage 1: Extract through-lines from themes and trades."""
        try:
            raw_response = self.client.generate(
                config=self.throughline_config,
                system=self.throughline_prompt,
                user=json.dumps(input_data, indent=2),
            )

            cleaned = _clean_json_response(raw_response)
            return json.loads(cleaned)

        except json.JSONDecodeError as e:
            print(f"  Stage 1 JSON parse error: {e}")
            return None
        except Exception as e:
            print(f"  Stage 1 error: {e}")
            return None

    def _stage2_callouts(self, through_lines: list[dict]) -> list[dict] | None:
        """Stage 2: Extract callouts from through-lines."""
        try:
            stage2_input = {"through_lines": through_lines}

            raw_response = self.client.generate(
                config=self.callout_config,
                system=self.callout_prompt,
                user=json.dumps(stage2_input, indent=2),
            )

            cleaned = _clean_json_response(raw_response)
            data = json.loads(cleaned)
            return data.get("callouts", [])

        except json.JSONDecodeError as e:
            print(f"  Stage 2 JSON parse error: {e}")
            return None
        except Exception as e:
            print(f"  Stage 2 error: {e}")
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

        def _parse_source_date(value: Any) -> date | None:
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
            if isinstance(value, str) and value.strip():
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return parsed.date()
                except ValueError:
                    return None
            return None

        for doc in documents:
            parsed_data = doc.get("parsed_data", {})
            if not parsed_data:
                continue

            source = doc.get("source", "Unknown")
            doc_name = doc.get("document_name", "Unknown Document")
            source_date = doc.get("source_date")

            sources.add(source)
            parsed_date = _parse_source_date(source_date)
            if parsed_date:
                dates.append(parsed_date)

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
            date_range = f"{dates_sorted[0].isoformat()} to {dates_sorted[-1].isoformat()}"
        else:
            date_range = datetime.now().strftime("%Y-%m-%d")

        return {
            "themes": themes,
            "trades": trades,
            "document_count": len(documents),
            "sources": list(sources),
            "date_range": date_range,
        }
