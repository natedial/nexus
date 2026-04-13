"""Deterministic chunking over normalized themes."""

from __future__ import annotations

from research_analysis_layer.models import AnalysisChunkDraft, HydratedParsedDocument


class Chunker:
    """Create one analysis chunk per normalized theme."""

    _CLASSIFICATION_TO_CHUNK_TYPE = {
        "Forecast": "forecast_block",
        "Opinion": "market_view",
        "Description": "data_interpretation",
    }

    def chunk_document(self, document: HydratedParsedDocument) -> list[AnalysisChunkDraft]:
        chunks: list[AnalysisChunkDraft] = []
        for idx, hydrated_theme in enumerate(document.themes, start=1):
            theme = hydrated_theme.theme
            excerpt_text = " ".join(
                excerpt.excerpt_text.strip()
                for excerpt in hydrated_theme.excerpts
                if excerpt.excerpt_text.strip()
            )
            chunk_text = theme.context.strip() or excerpt_text.strip() or theme.label.strip()
            chunk_type = self._CLASSIFICATION_TO_CHUNK_TYPE.get(
                theme.classification,
                "misc_context",
            )
            chunks.append(
                AnalysisChunkDraft(
                    chunk_order=idx,
                    chunk_type=chunk_type,
                    title=theme.label.strip() or f"Theme {idx}",
                    text=chunk_text,
                    section_name=theme.primary_category,
                    topic_tags=list(theme.relevance),
                    horizon_tag="forward" if theme.classification == "Forecast" else None,
                    parser_theme_id=theme.id,
                )
            )
        return chunks
