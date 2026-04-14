"""Typed models for bounded agent input payloads."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from pydantic import BaseModel, Field


class AgentInputDocument(BaseModel):
    """Document metadata shared with all specialist agents."""

    research_id: int
    file_id: str | None = None
    document_hash: str | None = None
    document_name: str
    document_title: str | None = None
    source: str | None = None
    source_date: str | None = None
    publisher: str | None = None
    area: str | None = None
    region: str | None = None
    asset_focus: str | None = None
    document_link: str | None = None
    trade_count: int = 0
    theme_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    full_text_excerpt: str | None = None


class AgentInputTheme(BaseModel):
    """Theme-level signal from the parser-owned normalization pass."""

    theme_id: int
    theme_order: int
    label: str
    scope: str | None = None
    primary_category: str | None = None
    relevance: list[str] = Field(default_factory=list)
    classification: str
    strength: str
    confidence: str
    evidence_count: int = 0
    mention_count: int = 0
    context: str = ""
    directionality: dict[str, Any] | None = None
    argument_structure: dict[str, Any] | None = None
    excerpts: list[str] = Field(default_factory=list)


class AgentInputChunk(BaseModel):
    """Chunk-level deterministic context."""

    chunk_order: int
    chunk_type: str
    title: str
    text: str | None = None
    section_name: str | None = None
    topic_tags: list[str] = Field(default_factory=list)
    entity_tags: list[str] = Field(default_factory=list)
    horizon_tag: str | None = None
    parser_theme_id: int | None = None


class AgentInputEvidenceUnit(BaseModel):
    """Evidence unit attached to a deterministic chunk."""

    chunk_order: int
    evidence_order: int
    evidence_type: str
    text: str | None = None
    normalized_text: str | None = None
    page_ref: str | None = None
    source_ref: dict[str, Any] | None = Field(default_factory=dict)
    parser_theme_id: int | None = None


class AgentInputAssertion(BaseModel):
    """Deterministic assertion extracted from the document."""

    chunk_order: int
    assertion_order: int
    assertion_type: str
    text: str | None = None
    summary_text: str | None = None
    polarity: str = "not_applicable"
    confidence_label: str = "medium"
    extraction_confidence: str = "medium"
    time_horizon: str = "unknown"
    time_anchor: str | None = None
    condition_text: str | None = None
    qualifier_text: str | None = None
    status: str = "proposed"
    authority_band: str = "seed"
    subject_text: str | None = None
    object_text: str | None = None


class DeterministicAnalysisPayload(BaseModel):
    """Structured deterministic signal available to all agents."""

    chunks: list[AgentInputChunk] = Field(default_factory=list)
    evidence_units: list[AgentInputEvidenceUnit] = Field(default_factory=list)
    assertions: list[AgentInputAssertion] = Field(default_factory=list)


class AgentInputPayload(BaseModel):
    """Canonical first-message payload shared across specialist agents."""

    agent_type: str
    document: AgentInputDocument
    themes: list[AgentInputTheme] = Field(default_factory=list)
    deterministic_analysis: DeterministicAnalysisPayload


def render_payload_structure_markdown() -> str:
    """Render the prompt component that documents the first user message."""

    return dedent(
        """
        ## Input payload structure

        The first user message is a JSON object — not raw document text. Parse it and use the richest available signal. Structure:

        ```json
        {
          "agent_type": "<string>",
          "document": {
            "research_id": <int>,
            "file_id": "<drive/file id or null>",
            "document_hash": "<sha256 or null>",
            "document_name": "<filename>",
            "document_title": "<string or null>",
            "source": "<publisher code or null>",
            "source_date": "<YYYY-MM-DD or null>",
            "publisher": "<string or null>",
            "area": "<macro | rates | fx | ... | null>",
            "region": "<string or null>",
            "asset_focus": "<string or null>",
            "document_link": "<url or null>",
            "trade_count": <int>,
            "theme_count": <int>,
            "metadata": {"<key>": "<json-safe value>", "...": "..."},
            "full_text_excerpt": "<up to 12k chars, may be truncated with ...>"
          },
          "themes": [
            {
              "theme_id": <int>,
              "theme_order": <int>,
              "label": "<short theme name>",
              "scope": "<string or null>",
              "primary_category": "<string or null>",
              "relevance": ["<tag>", "..."],
              "classification": "<string>",
              "strength": "<string>",
              "confidence": "<string label from parser>",
              "evidence_count": <int>,
              "mention_count": <int>,
              "context": "<up to 1.2k chars>",
              "directionality": {"<key>": "<json-safe value>", "...": "..."} | null,
              "argument_structure": {"<key>": "<json-safe value>", "...": "..."} | null,
              "excerpts": ["<excerpt>", "..."]
            }
          ],
          "deterministic_analysis": {
            "chunks": [
              {
                "chunk_order": <int>,
                "chunk_type": "<string>",
                "title": "<string>",
                "text": "<up to 900 chars>",
                "section_name": "<string or null>",
                "topic_tags": ["<tag>", "..."],
                "entity_tags": ["<entity>", "..."],
                "horizon_tag": "<string or null>",
                "parser_theme_id": <int or null>
              }
            ],
            "evidence_units": [
              {
                "chunk_order": <int>,
                "evidence_order": <int>,
                "evidence_type": "<string>",
                "text": "<up to 400 chars>",
                "normalized_text": "<up to 400 chars or null>",
                "page_ref": "<string or null>",
                "source_ref": {"<key>": "<json-safe value>", "...": "..."},
                "parser_theme_id": <int or null>
              }
            ],
            "assertions": [
              {
                "chunk_order": <int>,
                "assertion_order": <int>,
                "assertion_type": "<claim|forecast|risk|...>",
                "text": "<up to 500 chars>",
                "summary_text": "<up to 500 chars>",
                "polarity": "<positive|negative|neutral|not_applicable>",
                "confidence_label": "<low|medium|high>",
                "extraction_confidence": "<low|medium|high>",
                "time_horizon": "<intraday|days|weeks|months|longer|unknown>",
                "time_anchor": "<string or null>",
                "condition_text": "<string or null>",
                "qualifier_text": "<string or null>",
                "status": "<proposed|supported|contested|unknown>",
                "authority_band": "<low|medium|high|seed>",
                "subject_text": "<string or null>",
                "object_text": "<string or null>"
              }
            ]
          }
        }
        ```

        **Use the pre-extracted signal.** `deterministic_analysis.assertions` is already typed with polarity, time horizon, and authority — do not re-derive these from the excerpt. `themes[].directionality` and `themes[].strength` are your fastest path to the document's stance. Reach for `document.full_text_excerpt` only when the themes and assertions are silent on a point you need.

        ## Empty-payload fallback

        Not every parser run produces rich signal. Before working, check the payload and follow this ladder:

        1. If `deterministic_analysis.assertions[]` is non-empty, use it as your primary source.
        2. Else if `themes[]` is non-empty, work from `themes[].excerpts[]` and `themes[].context`.
        3. Else if `document.full_text_excerpt` is a non-empty string, read it directly.
        4. Else — all three are empty — do not fabricate analysis. Return a single summary sentence stating that the document lacks analyzable content, leave `key_claims` empty, and set `confidence` to `0.0`. This is the correct, honest outcome; downstream consumers filter by confidence.

        Do not mix ladder rungs. If rung 1 is available, do not also reach to rung 3 "for color" — it just adds noise and hurts reproducibility.
        """
    ).strip()
