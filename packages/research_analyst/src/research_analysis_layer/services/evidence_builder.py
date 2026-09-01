"""Build evidence units from retrieval chunks/spans or extraction themes."""

from __future__ import annotations

from research_analysis_layer.models import AnalysisChunkDraft, EvidenceUnitDraft, HydratedParsedDocument
from research_analysis_layer.models.assertion_models import normalize_text


class EvidenceBuilder:
    """Create deterministic evidence units, citing span_key when present."""

    def build_evidence(
        self,
        chunks: list[AnalysisChunkDraft],
        document: HydratedParsedDocument,
    ) -> list[EvidenceUnitDraft]:
        theme_by_id = {
            hydrated.theme.id: hydrated
            for hydrated in document.themes
        }
        span_by_key = {span.span_key: span for span in document.spans if span.span_key}
        evidence: list[EvidenceUnitDraft] = []
        for chunk in chunks:
            if chunk.span_keys:
                evidence.extend(self._from_span_keys(chunk, span_by_key))
                continue
            if chunk.parser_theme_id is not None:
                evidence.extend(self._from_theme(chunk, theme_by_id.get(chunk.parser_theme_id)))
                continue
            if chunk.text:
                evidence.append(
                    EvidenceUnitDraft(
                        chunk_order=chunk.chunk_order,
                        evidence_order=1,
                        evidence_type="chunk_text",
                        text=chunk.text,
                        normalized_text=normalize_text(chunk.text),
                        source_ref=self._source_ref(chunk),
                        parser_theme_id=chunk.parser_theme_id,
                    )
                )
        return evidence

    def _from_span_keys(
        self,
        chunk: AnalysisChunkDraft,
        span_by_key: dict,
    ) -> list[EvidenceUnitDraft]:
        units: list[EvidenceUnitDraft] = []
        for order, span_key in enumerate(chunk.span_keys, start=1):
            span = span_by_key.get(span_key)
            text = (span.text if span else "") or chunk.text
            if not text:
                continue
            page_ref = None
            if span and span.page_start is not None:
                page_ref = str(span.page_start)
            elif chunk.page_start is not None:
                page_ref = str(chunk.page_start)
            units.append(
                EvidenceUnitDraft(
                    chunk_order=chunk.chunk_order,
                    evidence_order=order,
                    evidence_type="span",
                    text=text,
                    normalized_text=normalize_text(text),
                    page_ref=page_ref,
                    source_ref=self._source_ref(chunk, span_key=span_key),
                    parser_theme_id=chunk.parser_theme_id,
                )
            )
        if units:
            return units
        if chunk.text:
            return [
                EvidenceUnitDraft(
                    chunk_order=chunk.chunk_order,
                    evidence_order=1,
                    evidence_type="chunk_text",
                    text=chunk.text,
                    normalized_text=normalize_text(chunk.text),
                    source_ref=self._source_ref(chunk),
                    parser_theme_id=chunk.parser_theme_id,
                )
            ]
        return []

    def _from_theme(self, chunk: AnalysisChunkDraft, hydrated_theme) -> list[EvidenceUnitDraft]:
        units: list[EvidenceUnitDraft] = []
        order = 1
        units.append(
            EvidenceUnitDraft(
                chunk_order=chunk.chunk_order,
                evidence_order=order,
                evidence_type="theme_label",
                text=chunk.title,
                normalized_text=normalize_text(chunk.title),
                source_ref={"chunk_order": chunk.chunk_order},
                parser_theme_id=chunk.parser_theme_id,
            )
        )
        order += 1
        if chunk.text:
            units.append(
                EvidenceUnitDraft(
                    chunk_order=chunk.chunk_order,
                    evidence_order=order,
                    evidence_type="theme_context",
                    text=chunk.text,
                    normalized_text=normalize_text(chunk.text),
                    source_ref={"chunk_order": chunk.chunk_order},
                    parser_theme_id=chunk.parser_theme_id,
                )
            )
            order += 1
        if hydrated_theme is None:
            return units
        for excerpt in hydrated_theme.excerpts:
            units.append(
                EvidenceUnitDraft(
                    chunk_order=chunk.chunk_order,
                    evidence_order=order,
                    evidence_type="excerpt",
                    text=excerpt.excerpt_text,
                    normalized_text=normalize_text(excerpt.excerpt_text),
                    source_ref={"excerpt_order": excerpt.excerpt_order},
                    parser_theme_id=chunk.parser_theme_id,
                )
            )
            order += 1
        return units

    @staticmethod
    def _source_ref(chunk: AnalysisChunkDraft, span_key: str | None = None) -> dict:
        ref: dict = {"chunk_order": chunk.chunk_order}
        if span_key:
            ref["span_key"] = span_key
        if chunk.retrieval_chunk_key:
            ref["retrieval_chunk_key"] = chunk.retrieval_chunk_key
        return ref
