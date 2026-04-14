"""Build bounded JSON payloads for analysis agents."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from research_analysis_layer.models import (
    AnalysisChunkDraft,
    AgentInputAssertion,
    AgentInputChunk,
    AgentInputDocument,
    AgentInputEvidenceUnit,
    AgentInputPayload,
    AgentInputTheme,
    AssertionDraft,
    DeterministicAnalysisPayload,
    EvidenceUnitDraft,
    HydratedParsedDocument,
)


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


class AgentInputBuilder:
    """Create stable, size-bounded input payloads for LLM agents."""

    def __init__(
        self,
        *,
        max_full_text_chars: int = 12000,
        max_theme_context_chars: int = 1200,
        max_excerpt_chars: int = 500,
        max_excerpts_per_theme: int = 3,
        max_chunk_chars: int = 900,
        max_evidence_chars: int = 400,
        max_assertion_chars: int = 500,
    ):
        self.max_full_text_chars = max_full_text_chars
        self.max_theme_context_chars = max_theme_context_chars
        self.max_excerpt_chars = max_excerpt_chars
        self.max_excerpts_per_theme = max_excerpts_per_theme
        self.max_chunk_chars = max_chunk_chars
        self.max_evidence_chars = max_evidence_chars
        self.max_assertion_chars = max_assertion_chars

    def build(
        self,
        *,
        agent_type: str,
        document: HydratedParsedDocument,
        chunks: list[AnalysisChunkDraft],
        evidence_units: list[EvidenceUnitDraft],
        assertions: list[AssertionDraft],
    ) -> dict[str, object]:
        parsed_data = document.document.parsed_data
        metadata = (
            parsed_data.get("metadata", {}) if isinstance(parsed_data, dict) else {}
        )
        full_text = (
            parsed_data.get("full_text") if isinstance(parsed_data, dict) else None
        )
        payload = AgentInputPayload(
            agent_type=agent_type,
            document=AgentInputDocument(
                research_id=document.research_id,
                file_id=document.file_id,
                document_hash=document.document_hash,
                document_name=document.document.document_name,
                document_title=document.document.document_title,
                source=document.document.source,
                source_date=document.document.source_date,
                publisher=document.document.publisher,
                area=document.document.area,
                region=document.document.region,
                asset_focus=document.document.asset_focus,
                document_link=document.document.document_link,
                trade_count=document.document.trade_count,
                theme_count=document.document.theme_count,
                metadata=metadata,
                full_text_excerpt=_truncate(
                    full_text if isinstance(full_text, str) else None,
                    self.max_full_text_chars,
                ),
            ),
            themes=[
                AgentInputTheme(
                    theme_id=hydrated.theme.id,
                    theme_order=hydrated.theme.theme_order,
                    label=hydrated.theme.label,
                    scope=hydrated.theme.scope,
                    primary_category=hydrated.theme.primary_category,
                    relevance=list(hydrated.theme.relevance),
                    classification=hydrated.theme.classification,
                    strength=hydrated.theme.strength,
                    confidence=hydrated.theme.confidence,
                    evidence_count=hydrated.theme.evidence_count,
                    mention_count=hydrated.theme.mention_count,
                    context=_truncate(
                        hydrated.theme.context,
                        self.max_theme_context_chars,
                    )
                    or "",
                    directionality=hydrated.theme.directionality,
                    argument_structure=hydrated.theme.argument_structure,
                    excerpts=[
                        excerpt_text
                        for excerpt_text in (
                            _truncate(excerpt.excerpt_text, self.max_excerpt_chars)
                            for excerpt in hydrated.excerpts[
                                : self.max_excerpts_per_theme
                            ]
                            if excerpt.excerpt_text.strip()
                        )
                        if excerpt_text
                    ],
                )
                for hydrated in document.themes
            ],
            deterministic_analysis=DeterministicAnalysisPayload(
                chunks=[
                    AgentInputChunk(**self._chunk_dict(chunk)) for chunk in chunks
                ],
                evidence_units=[
                    AgentInputEvidenceUnit(**self._evidence_dict(unit))
                    for unit in evidence_units
                ],
                assertions=[
                    AgentInputAssertion(**self._assertion_dict(assertion))
                    for assertion in assertions
                ],
            ),
        )
        return payload.model_dump(mode="python")

    def _chunk_dict(self, chunk: AnalysisChunkDraft) -> dict[str, object]:
        return {
            "chunk_order": chunk.chunk_order,
            "chunk_type": chunk.chunk_type,
            "title": chunk.title,
            "text": _truncate(chunk.text, self.max_chunk_chars),
            "section_name": chunk.section_name,
            "topic_tags": list(chunk.topic_tags),
            "entity_tags": list(chunk.entity_tags),
            "horizon_tag": chunk.horizon_tag,
            "parser_theme_id": chunk.parser_theme_id,
        }

    def _evidence_dict(self, unit: EvidenceUnitDraft) -> dict[str, object]:
        source_ref = unit.source_ref
        if is_dataclass(source_ref):
            source_ref = asdict(source_ref)
        return {
            "chunk_order": unit.chunk_order,
            "evidence_order": unit.evidence_order,
            "evidence_type": unit.evidence_type,
            "text": _truncate(unit.text, self.max_evidence_chars),
            "normalized_text": _truncate(unit.normalized_text, self.max_evidence_chars),
            "page_ref": unit.page_ref,
            "source_ref": self._json_safe(source_ref),
            "parser_theme_id": unit.parser_theme_id,
        }

    def _assertion_dict(self, assertion: AssertionDraft) -> dict[str, object]:
        return {
            "chunk_order": assertion.chunk_order,
            "assertion_order": assertion.assertion_order,
            "assertion_type": assertion.assertion_type,
            "text": _truncate(assertion.text, self.max_assertion_chars),
            "summary_text": _truncate(assertion.summary_text, self.max_assertion_chars),
            "polarity": assertion.polarity,
            "confidence_label": assertion.confidence_label,
            "extraction_confidence": assertion.extraction_confidence,
            "time_horizon": assertion.time_horizon,
            "time_anchor": assertion.time_anchor,
            "condition_text": assertion.condition_text,
            "qualifier_text": assertion.qualifier_text,
            "status": assertion.status,
            "authority_band": assertion.authority_band,
            "subject_text": assertion.subject_text,
            "object_text": assertion.object_text,
        }

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {
                str(key): AgentInputBuilder._json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [AgentInputBuilder._json_safe(item) for item in value]
        return value

    def to_messages(self, input_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert merged input data to Anthropic-shaped messages.

        Args:
            input_data: Dict with 'base', 'specialists', etc. from round config

        Returns:
            List of message dicts suitable for Anthropic messages API
        """
        import json

        messages = []

        if "base" in input_data:
            base = input_data["base"]
            base_text = json.dumps(base, ensure_ascii=True, sort_keys=True)
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": base_text}],
                }
            )

        for round_name, round_data in input_data.items():
            if round_name == "base" or round_name == "last_result":
                continue
            if isinstance(round_data, list):
                for angle in round_data:
                    if hasattr(angle, "model_dump"):
                        angle_dict = angle.model_dump()
                    else:
                        angle_dict = angle
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        angle_dict, ensure_ascii=True, sort_keys=True
                                    ),
                                }
                            ],
                        }
                    )

        if "last_result" in input_data:
            last = input_data["last_result"]
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(last, ensure_ascii=True, sort_keys=True),
                        }
                    ],
                }
            )

        return messages
