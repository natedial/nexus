"""Deterministic chunking over retrieval chunks, spans, or extraction themes."""

from __future__ import annotations

from research_analysis_layer.models import (
    AnalysisChunkDraft,
    HydratedParsedDocument,
    ParsedRetrievalChunk,
    ParsedSpan,
)


_USABLE_SPAN_KINDS = {"paragraph", "heading", "table", "figure", "text"}

_CLASSIFICATION_TO_CHUNK_TYPE = {
    "Forecast": "forecast_block",
    "Opinion": "market_view",
    "Description": "data_interpretation",
}


class Chunker:
    """Create analysis chunks from parser spans/chunks, falling back to themes."""

    def chunk_document(self, document: HydratedParsedDocument) -> list[AnalysisChunkDraft]:
        if document.retrieval_chunks:
            return self._from_retrieval_chunks(document)
        if document.spans:
            return self._from_spans(document)
        return self._from_themes(document)

    def _from_retrieval_chunks(
        self, document: HydratedParsedDocument
    ) -> list[AnalysisChunkDraft]:
        span_by_key = {span.span_key: span for span in document.spans if span.span_key}
        chunks: list[AnalysisChunkDraft] = []
        for idx, retrieval in enumerate(document.retrieval_chunks, start=1):
            pages = [
                span_by_key[key].page_start
                for key in retrieval.span_keys
                if key in span_by_key and span_by_key[key].page_start is not None
            ]
            chunks.append(
                AnalysisChunkDraft(
                    chunk_order=idx,
                    chunk_type="retrieval_chunk",
                    title=self._retrieval_title(retrieval, idx),
                    text=retrieval.chunk_text.strip(),
                    section_name="/".join(retrieval.heading_path) or None,
                    span_keys=list(retrieval.span_keys),
                    retrieval_chunk_key=retrieval.chunk_key or None,
                    page_start=min(pages) if pages else retrieval.page_start,
                    page_end=max(pages) if pages else retrieval.page_end,
                )
            )
        return chunks

    def _from_spans(self, document: HydratedParsedDocument) -> list[AnalysisChunkDraft]:
        chunks: list[AnalysisChunkDraft] = []
        order = 0
        for span in document.spans:
            if not self._usable_span(span):
                continue
            order += 1
            title = span.heading_path[-1] if span.heading_path else (span.span_key or f"Span {order}")
            chunks.append(
                AnalysisChunkDraft(
                    chunk_order=order,
                    chunk_type="span",
                    title=title,
                    text=span.text.strip(),
                    section_name="/".join(span.heading_path) or None,
                    span_keys=[span.span_key] if span.span_key else [],
                    page_start=span.page_start,
                    page_end=span.page_end,
                )
            )
        return chunks

    def _from_themes(self, document: HydratedParsedDocument) -> list[AnalysisChunkDraft]:
        chunks: list[AnalysisChunkDraft] = []
        for idx, hydrated_theme in enumerate(document.themes, start=1):
            theme = hydrated_theme.theme
            excerpt_text = " ".join(
                excerpt.excerpt_text.strip()
                for excerpt in hydrated_theme.excerpts
                if excerpt.excerpt_text.strip()
            )
            chunk_text = theme.context.strip() or excerpt_text.strip() or theme.label.strip()
            chunk_type = _CLASSIFICATION_TO_CHUNK_TYPE.get(
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

    @staticmethod
    def _retrieval_title(retrieval: ParsedRetrievalChunk, order: int) -> str:
        if retrieval.heading_path:
            return retrieval.heading_path[-1]
        if retrieval.chunk_key:
            return retrieval.chunk_key
        return f"Chunk {order}"

    @staticmethod
    def _usable_span(span: ParsedSpan) -> bool:
        if not span.text.strip():
            return False
        if not span.span_kind:
            return True
        return span.span_kind.lower() in _USABLE_SPAN_KINDS
