"""Build evidence units from chunks and parser themes."""

from __future__ import annotations

from research_analysis_layer.models import AnalysisChunkDraft, EvidenceUnitDraft, HydratedParsedDocument
from research_analysis_layer.models.assertion_models import normalize_text


class EvidenceBuilder:
    """Create deterministic evidence units from theme content."""

    def build_evidence(
        self,
        chunks: list[AnalysisChunkDraft],
        document: HydratedParsedDocument,
    ) -> list[EvidenceUnitDraft]:
        theme_by_id = {
            hydrated.theme.id: hydrated
            for hydrated in document.themes
        }
        evidence: list[EvidenceUnitDraft] = []
        for chunk in chunks:
            order = 1
            evidence.append(
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
                evidence.append(
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

            hydrated_theme = theme_by_id.get(chunk.parser_theme_id)
            if hydrated_theme is None:
                continue
            for excerpt in hydrated_theme.excerpts:
                evidence.append(
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
        return evidence
