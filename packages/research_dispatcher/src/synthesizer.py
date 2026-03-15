"""Cross-document synthesis using LLM with optional skill-based pipeline."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from .llm import (
    LLMClient,
    ModelConfig,
    load_model_config,
    load_optional_skill_config,
    load_skill_config,
)
from .stage1_profiles import (
    apply_payload_limits,
    build_stage1_prompt,
    stage1_profile_from_model_config,
)
from .trade_normalization import dedupe_text_items, normalize_trade_expression


# Prompt paths
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "synthesis.md"
SKILL_PROMPTS_PATH = Path(__file__).parent.parent / "prompts" / "skills"
COMPONENTS_PATH = Path(__file__).parent.parent / "prompts" / "components"
MARKET_EDGE_LENS_PATH = COMPONENTS_PATH / "market_edge_lens.md"
CALLOUT_SELECTION_LENS_PATH = COMPONENTS_PATH / "callout_selection_lens.md"


def _load_prompt(filename: str = "synthesis.md") -> str:
    """Load prompt from markdown file."""
    if filename == "synthesis.md":
        prompt = PROMPT_PATH.read_text().strip()
    else:
        prompt = (SKILL_PROMPTS_PATH / filename).read_text().strip()

    if filename in {"synthesis.md", "throughline_synthesizer.md", "throughline_analyst.md"}:
        lens = MARKET_EDGE_LENS_PATH.read_text().strip()
        return f"{prompt}\n\n---\n\n{lens}"

    if filename == "callout_extractor.md":
        lens = CALLOUT_SELECTION_LENS_PATH.read_text().strip()
        return f"{prompt}\n\n---\n\n{lens}"

    return prompt


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


def _dump_json_payload(data: Any) -> str:
    """Serialize JSON payloads compactly to reduce token pressure."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


@dataclass
class SynthesisResult:
    """Result of cross-document synthesis."""

    title: str
    document_count: int
    through_lines: list[dict]
    callouts: list[dict]
    analysis_paragraphs: list[dict[str, Any]] = field(default_factory=list)
    raw_response: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for report."""
        return {
            "title": self.title,
            "document_count": self.document_count,
            "through_lines": self.through_lines,
            "callouts": self.callouts,
            "analysis_paragraphs": self.analysis_paragraphs,
        }


class Synthesizer:
    """Performs cross-document synthesis using LLM."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        deepinfra_api_key: str | None = None,
        use_skill_pipeline: bool = False,
    ):
        self.client = LLMClient(
            anthropic_api_key=anthropic_api_key,
            openai_api_key=openai_api_key,
            deepinfra_api_key=deepinfra_api_key,
        )
        self.use_skill_pipeline = use_skill_pipeline

        # Load monolithic config/prompt
        self.config = load_model_config()
        self.prompt = _load_prompt()

        # Skill configs (lazy-loaded)
        self._throughline_config: ModelConfig | None = None
        self._throughline_fallback_configs: list[ModelConfig] | None = None
        self._callout_config: ModelConfig | None = None
        self._throughline_prompt: str | None = None
        self._callout_prompt: str | None = None
        self._throughline_analyst_config: ModelConfig | None = None
        self._throughline_analyst_prompt: str | None = None
        self._throughline_analyst_editor_config: ModelConfig | None = None
        self._throughline_analyst_editor_prompt: str | None = None

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
    def throughline_analyst_config(self) -> ModelConfig | None:
        """Optional config for a PM-facing analyst writeup after through-lines are edited."""
        if not hasattr(self, "_throughline_analyst_config_loaded"):
            self._throughline_analyst_config = load_optional_skill_config("throughline_analyst")
            self._throughline_analyst_config_loaded = True
        return self._throughline_analyst_config

    @property
    def throughline_analyst_editor_config(self) -> ModelConfig | None:
        """Optional config for a post-processing editor on the PM-facing analysis writeup."""
        if not hasattr(self, "_throughline_analyst_editor_config_loaded"):
            self._throughline_analyst_editor_config = load_optional_skill_config(
                "throughline_analyst_editor"
            )
            self._throughline_analyst_editor_config_loaded = True
        return self._throughline_analyst_editor_config

    @property
    def throughline_editor_config(self) -> ModelConfig | None:
        """Optional config for a post-processing through-line editor."""
        if not hasattr(self, "_throughline_editor_config"):
            self._throughline_editor_config = load_optional_skill_config("throughline_editor")
        return self._throughline_editor_config

    @property
    def throughline_fallback_configs(self) -> list[ModelConfig]:
        """Optional fallback configs for stage-one throughline synthesis, in order."""
        if self._throughline_fallback_configs is None:
            fallbacks: list[ModelConfig] = []
            for skill_name in (
                "throughline_synthesizer_fallback",
                "throughline_synthesizer_secondary_fallback",
            ):
                config = load_optional_skill_config(skill_name)
                if config is not None:
                    fallbacks.append(config)
            self._throughline_fallback_configs = fallbacks
        return self._throughline_fallback_configs

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

    @property
    def throughline_editor_prompt(self) -> str:
        """Lazy-load through-line editor prompt."""
        if not hasattr(self, "_throughline_editor_prompt") or self._throughline_editor_prompt is None:
            self._throughline_editor_prompt = _load_prompt("throughline_editor.md")
        return self._throughline_editor_prompt

    @property
    def throughline_analyst_prompt(self) -> str:
        """Lazy-load through-line analyst prompt."""
        if self._throughline_analyst_prompt is None:
            self._throughline_analyst_prompt = _load_prompt("throughline_analyst.md")
        return self._throughline_analyst_prompt

    @property
    def throughline_analyst_editor_prompt(self) -> str:
        """Lazy-load through-line analyst editor prompt."""
        if self._throughline_analyst_editor_prompt is None:
            self._throughline_analyst_editor_prompt = _load_prompt("throughline_analyst_editor.md")
        return self._throughline_analyst_editor_prompt

    def synthesize(
        self,
        documents: list[dict[str, Any]],
        scope: dict[str, Any] | None = None,
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
            return self._synthesize_with_skills(input_data, len(documents), scope or {})
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
            coerced_stage1 = self._coerce_stage1_result(data)
            through_lines = coerced_stage1.get("through_lines", [])
            self._normalize_through_lines(through_lines)
            callouts = data.get("callouts", [])
            self._normalize_callouts(callouts, through_lines)
            result = SynthesisResult(
                title=coerced_stage1.get("title", "Cross-Document Synthesis"),
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
        scope: dict[str, Any],
    ) -> SynthesisResult | None:
        """Multi-stage synthesis using extractor, editorial pass, and callout skills."""
        print("  Using skill-based pipeline...")

        # Stage 1A: Extract through-lines
        print("  Stage 1A: Extracting through-lines...")
        stage1_result = self._stage1_throughlines(input_data)

        if stage1_result is None:
            print("  Stage 1A failed, aborting synthesis")
            return None

        title = stage1_result.get("title", "Cross-Document Synthesis")
        through_lines = stage1_result.get("through_lines", [])

        if not through_lines:
            print("  Stage 1A returned no through-lines")
            return None

        raw_throughline_count = len(through_lines)

        # Stage 1B: editorial pass for readability and schema discipline
        if self.throughline_editor_config is not None:
            print(f"  Stage 1B: Editing {raw_throughline_count} through-lines...")
            edited_stage1_result = self._stage1_edit_throughlines(title, through_lines)
            if edited_stage1_result is not None:
                title = edited_stage1_result.get("title", title)
                through_lines = edited_stage1_result.get("through_lines", through_lines)
                print(
                    "  Stage 1B complete: "
                    f"{raw_throughline_count} raw -> {len(through_lines)} edited through-lines"
                )
            else:
                print("  Stage 1B failed, aborting synthesis")
                return None
        else:
            print("  Stage 1B skipped: no through-line editor configured")

        analysis_paragraphs: list[dict[str, Any]] = []
        if self.throughline_analyst_config is not None:
            print(f"  Stage 1C: Writing PM analysis from {len(through_lines)} through-lines...")
            analysis_result = self._stage1c_analyze_throughlines(
                title=title,
                through_lines=through_lines,
                input_data=input_data,
                scope=scope,
            )
            if analysis_result is not None:
                analysis_paragraphs = analysis_result.get("analysis_paragraphs", [])
                print(f"  Stage 1C complete: {len(analysis_paragraphs)} analysis paragraphs")
                if self.throughline_analyst_editor_config is not None:
                    print(f"  Stage 1D: Editing {len(analysis_paragraphs)} analysis paragraphs...")
                    edited_analysis_result = self._stage1d_edit_analysis(
                        title=title,
                        through_lines=through_lines,
                        input_data=input_data,
                        scope=scope,
                        analysis_paragraphs=analysis_paragraphs,
                    )
                    if edited_analysis_result is not None:
                        analysis_paragraphs = edited_analysis_result.get(
                            "analysis_paragraphs",
                            analysis_paragraphs,
                        )
                        print(
                            "  Stage 1D complete: "
                            f"{len(analysis_paragraphs)} edited analysis paragraphs"
                        )
                    else:
                        print("  Stage 1D failed validation, keeping Stage 1C analysis")
                else:
                    print("  Stage 1D skipped: no through-line analyst editor configured")
            else:
                print("  Stage 1C failed validation, continuing without analysis writeup")
        else:
            print("  Stage 1C skipped: no through-line analyst configured")

        print(f"  Stage 1 complete: {len(through_lines)} edited through-lines ready for callouts")

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
            analysis_paragraphs=analysis_paragraphs,
            raw_response=None,
        )
        print(f"Synthesis complete: {result.title}")
        print(f"  Through-lines: {len(result.through_lines)}")
        print(f"  Analysis paragraphs: {len(result.analysis_paragraphs)}")
        print(f"  Callouts: {len(result.callouts)}")
        return result

    def _stage1_throughlines(self, input_data: dict) -> dict | None:
        """Stage 1: Extract through-lines from themes and trades."""
        configs = [self.throughline_config]
        configs.extend(self.throughline_fallback_configs)

        for index, config in enumerate(configs, start=1):
            provider_label = f"{config.provider}:{config.model}"
            if index > 1:
                print(f"  Stage 1 fallback attempt {index - 1}: {provider_label}")

            try:
                stage1_profile = stage1_profile_from_model_config(provider_label, config)
                stage1_input = self._prepare_stage1_payload(
                    apply_payload_limits(input_data, stage1_profile),
                    config,
                )
                stage1_prompt = build_stage1_prompt(self.throughline_prompt, stage1_profile)
                raw_response = self.client.generate(
                    config=config,
                    system=stage1_prompt,
                    user=_dump_json_payload(stage1_input),
                )
                cleaned = _clean_json_response(raw_response)
                if not cleaned:
                    raise ValueError("Empty response body")
                return self._coerce_stage1_result(json.loads(cleaned))
            except json.JSONDecodeError as e:
                print(f"  Stage 1 JSON parse error via {provider_label}: {e}")
            except Exception as e:
                print(f"  Stage 1 error via {provider_label}: {e}")

        return None

    def _stage1_edit_throughlines(
        self,
        title: str,
        through_lines: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Stage 1.5: Use an editor model to tighten stage-one output without adding new claims."""
        editor_config = self.throughline_editor_config
        if editor_config is None:
            return None

        try:
            editor_input = {
                "title": title,
                "through_lines": through_lines,
            }
            raw_response = self.client.generate(
                config=editor_config,
                system=self.throughline_editor_prompt,
                user=_dump_json_payload(editor_input),
            )
            cleaned = _clean_json_response(raw_response)
            if not cleaned:
                raise ValueError("Empty editor response body")
            edited = self._coerce_stage1_result(json.loads(cleaned))
            if not edited.get("through_lines"):
                raise ValueError("Editor returned no through-lines")
            return edited
        except Exception as e:
            print(f"  Stage 1.5 editor error: {e}")
            return None

    def _stage2_callouts(self, through_lines: list[dict]) -> list[dict] | None:
        """Stage 2: Extract callouts from through-lines."""
        try:
            stage2_input = {"through_lines": through_lines}

            raw_response = self.client.generate(
                config=self.callout_config,
                system=self.callout_prompt,
                user=_dump_json_payload(stage2_input),
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

    def _stage1c_analyze_throughlines(
        self,
        title: str,
        through_lines: list[dict[str, Any]],
        input_data: dict[str, Any],
        scope: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Generate a PM-facing narrative writeup grounded in edited through-lines."""
        analyst_config = self.throughline_analyst_config
        if analyst_config is None:
            return None

        try:
            analyst_input = self._build_analysis_payload(
                title=title,
                through_lines=through_lines,
                input_data=input_data,
                scope=scope,
            )
            raw_response = self.client.generate(
                config=analyst_config,
                system=self.throughline_analyst_prompt,
                user=_dump_json_payload(analyst_input),
            )
            cleaned = _clean_json_response(raw_response)
            if not cleaned:
                raise ValueError("Empty analyst response body")
            return self._coerce_analysis_result(
                json.loads(cleaned),
                through_lines=through_lines,
            )
        except Exception as e:
            print(f"  Stage 1C analyst error: {e}")
            return None

    def _stage1d_edit_analysis(
        self,
        title: str,
        through_lines: list[dict[str, Any]],
        input_data: dict[str, Any],
        scope: dict[str, Any],
        analysis_paragraphs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Edit the Stage 1C writeup without loosening its grounding or coverage."""
        analyst_editor_config = self.throughline_analyst_editor_config
        if analyst_editor_config is None:
            return None

        try:
            analyst_editor_input = self._build_analysis_payload(
                title=title,
                through_lines=through_lines,
                input_data=input_data,
                scope=scope,
            )
            analyst_editor_input["analysis_paragraphs"] = analysis_paragraphs
            raw_response = self.client.generate(
                config=analyst_editor_config,
                system=self.throughline_analyst_editor_prompt,
                user=_dump_json_payload(analyst_editor_input),
            )
            cleaned = _clean_json_response(raw_response)
            if not cleaned:
                raise ValueError("Empty analyst editor response body")
            return self._coerce_analysis_result(
                json.loads(cleaned),
                through_lines=through_lines,
                expected_count=len(analysis_paragraphs),
            )
        except Exception as e:
            print(f"  Stage 1D analyst editor error: {e}")
            return None

    def _normalize_through_lines(self, through_lines: list[dict[str, Any]]) -> None:
        """Ensure through-lines have displayable source metadata."""
        for tl in through_lines:
            if not isinstance(tl, dict):
                continue
            tl["lead"] = " ".join(str(tl.get("lead", "")).split()).strip()
            tl["consensus_anchor"] = " ".join(str(tl.get("consensus_anchor", "")).split()).strip()
            tl["key_insight"] = " ".join(str(tl.get("key_insight", "")).split()).strip()
            tl["supporting_sources"] = dedupe_text_items(tl.get("supporting_sources"), limit=6)
            tl["supporting_themes"] = dedupe_text_items(tl.get("supporting_themes"), limit=6)
            tl["supporting_trades"] = self._normalize_supporting_trades(tl.get("supporting_trades"))
            if tl.get("source") or tl.get("document"):
                continue
            supporting_sources = tl.get("supporting_sources")
            if supporting_sources:
                tl["source"] = self._format_sources(supporting_sources)
                tl["document"] = "Cross-document synthesis"

    def _coerce_stage1_result(self, data: Any) -> dict[str, Any]:
        """Coerce model output into the expected stage-one schema before downstream normalization."""
        if not isinstance(data, dict):
            raise ValueError("Stage 1 response must be a JSON object")

        raw_lines = data.get("through_lines", [])
        if isinstance(raw_lines, dict):
            raw_lines = [raw_lines]
        elif not isinstance(raw_lines, list):
            raw_lines = []

        through_lines = []
        for raw_line in raw_lines:
            coerced = self._coerce_through_line(raw_line)
            if coerced:
                through_lines.append(coerced)

        title = self._clean_text(data.get("title")) or "Cross-Document Synthesis"
        return {
            "title": title,
            "through_lines": through_lines,
        }

    def _coerce_analysis_result(
        self,
        data: Any,
        through_lines: list[dict[str, Any]],
        expected_count: int | None = None,
    ) -> dict[str, Any]:
        """Validate Stage 1C/1D output so only grounded analysis reaches the report."""
        if not isinstance(data, dict):
            raise ValueError("Analysis response must be a JSON object")

        raw_paragraphs = data.get("analysis_paragraphs", [])
        if isinstance(raw_paragraphs, dict):
            raw_paragraphs = [raw_paragraphs]
        if not isinstance(raw_paragraphs, list):
            raise ValueError("analysis_paragraphs must be a list")
        if not 1 <= len(raw_paragraphs) <= 8:
            raise ValueError("analysis_paragraphs must contain 1 to 8 items")
        if expected_count is not None and len(raw_paragraphs) != expected_count:
            raise ValueError("analysis_paragraph count changed unexpectedly")

        allowed_leads = {
            self._clean_text(tl.get("lead"))
            for tl in through_lines
            if self._clean_text(tl.get("lead"))
        }
        allowed_theme_labels = {
            self._clean_text(label)
            for tl in through_lines
            for label in tl.get("supporting_themes", [])
            if self._clean_text(label)
        }

        paragraphs: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        covered_questions: set[int] = set()
        for raw_paragraph in raw_paragraphs:
            paragraph = self._coerce_analysis_paragraph(
                raw_paragraph,
                allowed_leads=allowed_leads,
                allowed_theme_labels=allowed_theme_labels,
            )
            normalized_text = paragraph["text"].lower()
            if normalized_text in seen_texts:
                raise ValueError("analysis_paragraphs contains duplicate text")
            seen_texts.add(normalized_text)
            covered_questions.update(paragraph["question_ids"])
            paragraphs.append(paragraph)

        if covered_questions != set(range(1, 11)):
            raise ValueError("analysis writeup must cover all ten market-edge questions")

        return {"analysis_paragraphs": paragraphs}

    def _coerce_analysis_paragraph(
        self,
        value: Any,
        allowed_leads: set[str],
        allowed_theme_labels: set[str],
    ) -> dict[str, Any]:
        """Normalize one analysis paragraph into the canonical renderable form."""
        if not isinstance(value, dict):
            raise ValueError("Each analysis paragraph must be an object")

        text = self._clean_text(value.get("text"))
        if not text:
            raise ValueError("Analysis paragraph text cannot be empty")

        through_line_leads = [
            lead for lead in self._coerce_string_list(value.get("through_line_leads"), limit=8)
            if lead in allowed_leads
        ]
        if not through_line_leads:
            raise ValueError("Analysis paragraph must reference at least one valid through-line lead")

        theme_labels = [
            label for label in self._coerce_string_list(value.get("theme_labels"), limit=10)
            if label in allowed_theme_labels
        ]
        if not theme_labels:
            raise ValueError("Analysis paragraph must reference at least one valid theme label")

        question_ids = self._coerce_question_ids(value.get("question_ids"))
        if not question_ids:
            raise ValueError("Analysis paragraph must reference at least one question id")

        return {
            "text": text,
            "through_line_leads": through_line_leads,
            "theme_labels": theme_labels,
            "question_ids": question_ids,
        }

    def _coerce_through_line(self, raw_line: Any) -> dict[str, Any] | None:
        """Coerce one through-line into the canonical schema."""
        if not isinstance(raw_line, dict):
            return None

        lead = self._clean_text(raw_line.get("lead") or raw_line.get("headline") or raw_line.get("summary"))
        key_insight = self._clean_text(raw_line.get("key_insight") or raw_line.get("insight") or raw_line.get("analysis"))
        if not lead and key_insight:
            lead = self._truncate_text(key_insight, 120)
        if not lead:
            return None

        supporting_sources = self._coerce_string_list(
            raw_line.get("supporting_sources") or raw_line.get("sources") or raw_line.get("source"),
            limit=6,
        )
        supporting_themes = self._coerce_string_list(
            raw_line.get("supporting_themes") or raw_line.get("themes"),
            limit=6,
        )
        supporting_trades = self._coerce_trade_items(
            raw_line.get("supporting_trades") or raw_line.get("trades")
        )

        return {
            "lead": lead,
            "supporting_sources": supporting_sources,
            "consensus_level": self._coerce_consensus_level(
                raw_line.get("consensus_level"),
                len(supporting_sources),
            ),
            "consensus_anchor": self._clean_text(
                raw_line.get("consensus_anchor") or raw_line.get("market_belief") or raw_line.get("anchor")
            ),
            "supporting_themes": supporting_themes,
            "supporting_trades": supporting_trades,
            "key_insight": key_insight or lead,
        }

    def _coerce_consensus_level(self, value: Any, source_count: int) -> str:
        """Map model-specific labels back into the canonical consensus enum."""
        normalized = self._clean_text(value).lower().replace("-", "_").replace(" ", "_")

        if "contrarian" in normalized:
            level = "contrarian"
        elif any(token in normalized for token in ("mixed_views", "mixed", "contested", "split", "diverg")):
            level = "mixed_views"
        elif any(token in normalized for token in ("strong_consensus", "high_consensus", "strong", "high")):
            level = "strong_consensus"
        elif any(token in normalized for token in ("moderate_consensus", "moderate", "medium_consensus", "medium")):
            level = "moderate_consensus"
        elif "low" in normalized:
            level = "contrarian"
        else:
            level = "moderate_consensus"

        # A single supporting source cannot justify a consensus label.
        if source_count <= 1 and level in {"strong_consensus", "moderate_consensus"}:
            return "contrarian"
        return level

    def _coerce_string_list(self, value: Any, limit: int = 6) -> list[str]:
        """Convert strings, dicts, or lists into a clean list of short strings."""
        if value is None:
            return []

        items: list[str] = []
        raw_items = value if isinstance(value, list) else [value]

        for item in raw_items:
            if isinstance(item, dict):
                candidate = (
                    item.get("label")
                    or item.get("text")
                    or item.get("name")
                    or item.get("source")
                    or item.get("document")
                )
                text = self._clean_text(candidate)
                if text:
                    items.append(text)
                continue

            if isinstance(item, str):
                parts = re.split(r"\s*[;\n|]\s*|\s*,\s*", item)
                cleaned_parts = [self._clean_text(part) for part in parts]
                if len(cleaned_parts) <= 1:
                    cleaned = self._clean_text(item)
                    if cleaned:
                        items.append(cleaned)
                else:
                    for part in cleaned_parts:
                        if part:
                            items.append(part)
                continue

            cleaned = self._clean_text(item)
            if cleaned:
                items.append(cleaned)

        return dedupe_text_items(items, limit=limit)

    def _coerce_trade_items(self, value: Any) -> list[str]:
        """Convert list/string/object trade variants into the canonical short trade-expression list."""
        if value is None:
            return []

        raw_items = value if isinstance(value, list) else [value]
        normalized: list[str] = []

        for item in raw_items:
            source = ""
            candidate = item
            if isinstance(item, dict):
                source = self._clean_text(item.get("source"))
                candidate = (
                    item.get("text")
                    or item.get("exposure")
                    or item.get("trade")
                    or item.get("rationale")
                )

            cleaned = normalize_trade_expression(self._clean_text(candidate))
            if not cleaned:
                continue
            if source and source.lower() not in cleaned.lower():
                cleaned = f"{cleaned} ({source})"
            normalized.append(cleaned)

        return dedupe_text_items(normalized, limit=2)

    def _coerce_question_ids(self, value: Any) -> list[int]:
        """Normalize question ids from strings or ints into the canonical 1-10 set."""
        if value is None:
            return []

        raw_items = value if isinstance(value, list) else [value]
        question_ids: list[int] = []
        for item in raw_items:
            if isinstance(item, int):
                candidate = item
            else:
                text = self._clean_text(item).upper()
                if text.startswith("Q"):
                    text = text[1:]
                if not text.isdigit():
                    continue
                candidate = int(text)

            if 1 <= candidate <= 10:
                question_ids.append(candidate)

        return sorted(set(question_ids))

    def _clean_text(self, value: Any) -> str:
        """Collapse arbitrary values into a single line of text."""
        return " ".join(str(value or "").split()).strip()

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

    def _normalize_supporting_trades(self, trades: Any) -> list[str]:
        """Keep supporting trades concise so through-lines read as narratives, not trade dumps."""
        if not isinstance(trades, list):
            return []

        normalized = []
        for trade in trades:
            cleaned = normalize_trade_expression(str(trade))
            if cleaned:
                normalized.append(cleaned)

        return dedupe_text_items(normalized, limit=2)

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

    def _build_analysis_payload(
        self,
        title: str,
        through_lines: list[dict[str, Any]],
        input_data: dict[str, Any],
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble a compact, grounded payload for the PM-facing Stage 1C analyst pass."""
        theme_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for theme in input_data.get("themes", []):
            if not isinstance(theme, dict):
                continue
            label = self._clean_text(theme.get("label"))
            if label:
                theme_index[label].append(theme)

        theme_clusters = []
        for through_line in through_lines:
            labels = through_line.get("supporting_themes") or []
            theme_entries = []
            for label in labels:
                evidence = []
                for theme in theme_index.get(label, [])[:3]:
                    evidence.append({
                        "source": self._clean_text(theme.get("source")),
                        "document": self._truncate_text(theme.get("document", ""), 72),
                        "context": self._truncate_text(theme.get("context", ""), 220),
                        "strength": self._clean_text(theme.get("strength")),
                        "confidence": self._clean_text(theme.get("confidence")),
                    })
                if evidence:
                    theme_entries.append({
                        "label": label,
                        "evidence": evidence,
                    })

            theme_clusters.append({
                "lead": through_line.get("lead", ""),
                "consensus_level": through_line.get("consensus_level", ""),
                "consensus_anchor": through_line.get("consensus_anchor", ""),
                "supporting_sources": through_line.get("supporting_sources", []),
                "supporting_themes": labels,
                "key_insight": through_line.get("key_insight", ""),
                "themes": theme_entries,
            })

        return {
            "scope": self._build_scope_context(scope, input_data),
            "title": title,
            "through_lines": through_lines,
            "theme_clusters": theme_clusters,
        }

    def _build_scope_context(
        self,
        scope: dict[str, Any],
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize report scope so the analyst stage stays aware of the active filter envelope."""
        return {
            "region": self._clean_text(scope.get("region")) or "All",
            "asset_focus": self._clean_text(scope.get("asset_focus")) or "All",
            "sources_filter": self._clean_text(scope.get("sources")) or "All",
            "date_range_days": int(scope.get("date_range_days") or 0),
            "source_date_range": self._clean_text(input_data.get("date_range")),
            "source_count": len(input_data.get("sources", [])),
            "document_count": int(input_data.get("document_count") or 0),
        }

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
                        theme_entry = {
                            "source": source,
                            "document": doc_name,
                            "label": theme.get("label", "Unlabeled"),
                            "context": theme.get("context", ""),
                            "strength": theme.get("strength", "Secondary"),
                            "confidence": theme.get("confidence", "Medium"),
                            "classification": theme.get("classification", "Description"),
                            "mention_count": theme.get("mention_count", 0),
                        }
                        # Include excerpts if present (verbatim quotes aid synthesis)
                        excerpts = theme.get("excerpts")
                        if excerpts and isinstance(excerpts, list):
                            theme_entry["excerpts"] = excerpts
                        # Include directionality if present (e.g. {"bullish": 3, "bearish": 1})
                        directionality = theme.get("directionality")
                        if directionality and isinstance(directionality, dict):
                            theme_entry["directionality"] = directionality
                        # Include relevance tags if present
                        relevance = theme.get("relevance")
                        if relevance and isinstance(relevance, list):
                            theme_entry["relevance"] = relevance
                        themes.append(theme_entry)

            # Extract trades with source attribution
            doc_trades = parsed_data.get("trades", [])
            if isinstance(doc_trades, list):
                for trade in doc_trades:
                    if isinstance(trade, dict):
                        trade_text = normalize_trade_expression(
                            trade.get("exposure") or trade.get("text", "")
                        )
                        if not trade_text:
                            continue
                        trades.append({
                            "source": source,
                            "document": doc_name,
                            "text": trade_text,
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

    def _prepare_stage1_payload(
        self,
        input_data: dict[str, Any],
        config: ModelConfig,
    ) -> dict[str, Any]:
        """Adapt stage-one payload by provider/model so smaller DeepInfra models do not drown in context."""
        if not self._should_compact_stage1_payload(config):
            return input_data

        return {
            "themes": [self._compact_theme_entry(theme) for theme in input_data.get("themes", [])],
            "trades": [self._compact_trade_entry(trade) for trade in input_data.get("trades", [])],
            "document_count": input_data.get("document_count", 0),
            "sources": input_data.get("sources", []),
            "date_range": input_data.get("date_range", ""),
        }

    def _should_compact_stage1_payload(self, config: ModelConfig) -> bool:
        """Use a lighter payload for DeepInfra non-instruct models where context size is the limiting factor."""
        if config.provider != "deepinfra":
            return False

        normalized = config.model.lower()
        if "instruct" in normalized:
            return False
        if "kimi-k2.5" in normalized:
            return True
        if "minimax-m2.5" in normalized:
            return True
        return False

    def _compact_theme_entry(self, theme: Any) -> dict[str, Any]:
        """Trim verbose theme fields while keeping the narrative spine intact."""
        if not isinstance(theme, dict):
            return {}

        compacted = {
            "source": theme.get("source", ""),
            "document": self._truncate_text(theme.get("document", ""), 72),
            "label": self._truncate_text(theme.get("label", ""), 120),
            "context": self._truncate_text(theme.get("context", ""), 220),
            "strength": theme.get("strength", ""),
            "confidence": theme.get("confidence", ""),
            "classification": theme.get("classification", ""),
            "mention_count": theme.get("mention_count", 0),
        }

        directionality = theme.get("directionality")
        if isinstance(directionality, dict) and directionality:
            compacted["directionality"] = directionality

        relevance = theme.get("relevance")
        if isinstance(relevance, list) and relevance:
            compacted["relevance"] = relevance[:4]

        return compacted

    def _compact_trade_entry(self, trade: Any) -> dict[str, Any]:
        """Trim trade entries to the executable expression and the minimal causal cue."""
        if not isinstance(trade, dict):
            return {}

        compacted = {
            "source": trade.get("source", ""),
            "document": self._truncate_text(trade.get("document", ""), 72),
            "text": self._truncate_text(trade.get("text", ""), 160),
            "conviction": trade.get("conviction", ""),
            "timeframe": trade.get("timeframe", ""),
        }

        rationale = self._truncate_text(trade.get("rationale", ""), 140)
        if rationale:
            compacted["rationale"] = rationale

        return compacted

    def _truncate_text(self, value: Any, max_length: int) -> str:
        """Trim long fields without leaving broken whitespace or giant filenames."""
        text = " ".join(str(value or "").split()).strip()
        if len(text) <= max_length:
            return text
        return text[: max_length - 3].rstrip() + "..."
