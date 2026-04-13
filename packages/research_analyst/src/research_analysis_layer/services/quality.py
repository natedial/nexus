"""Deterministic document-quality review."""

from __future__ import annotations

import json
import re

from research_analysis_layer.config import Settings
from research_analysis_layer.models import DocumentQualityReport, HydratedParsedDocument


KNOWN_SOURCE_ALIASES: dict[str, set[str]] = {
    "bank of america": {"bank", "america", "boa", "bofa", "merrill"},
    "barclays": {"barclays"},
    "deutsche bank": {"deutsche", "db"},
    "goldman sachs": {"goldman", "sachs", "gs"},
    "j p morgan": {"jpm", "jpmorgan", "morgan"},
    "jpmorgan": {"jpm", "jpmorgan", "morgan"},
    "j.p. morgan": {"jpm", "jpmorgan", "morgan"},
}


class QualityReviewer:
    """Score hydrated parser documents before analysis writes."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def review(self, document: HydratedParsedDocument) -> DocumentQualityReport:
        doc = document.document
        full_text = ""
        if isinstance(doc.parsed_data, dict):
            full_text = str(doc.parsed_data.get("full_text") or "")

        theme_count = len(document.themes)
        usable_theme_count = 0
        excerpt_theme_count = 0
        total_excerpt_chars = 0
        total_excerpt_count = 0
        non_empty_label_count = 0

        for hydrated_theme in document.themes:
            theme = hydrated_theme.theme
            label = theme.label.strip()
            context = theme.context.strip()
            excerpt_chars = sum(len(item.excerpt_text.strip()) for item in hydrated_theme.excerpts)
            if label:
                non_empty_label_count += 1
            if context or excerpt_chars:
                usable_theme_count += 1
            if hydrated_theme.excerpts:
                excerpt_theme_count += 1
            total_excerpt_chars += excerpt_chars
            total_excerpt_count += len(hydrated_theme.excerpts)

        usable_theme_ratio = usable_theme_count / theme_count if theme_count else 0.0
        excerpt_theme_ratio = excerpt_theme_count / theme_count if theme_count else 0.0
        average_excerpt_chars = (
            total_excerpt_chars / total_excerpt_count if total_excerpt_count else 0.0
        )
        non_empty_label_ratio = non_empty_label_count / theme_count if theme_count else 0.0

        source = (doc.source or "").strip()
        file_name = doc.document_name or ""
        blocking_issues: list[str] = []
        warnings: list[str] = []

        if not document.ready_for_analysis:
            blocking_issues.append("document_not_ready")
        if not source or source.lower() == "unknown":
            blocking_issues.append("missing_or_unknown_source")
        if len(full_text.strip()) < self.settings.min_full_text_chars:
            blocking_issues.append("full_text_too_short")
        if usable_theme_ratio < self.settings.min_usable_theme_ratio:
            blocking_issues.append("insufficient_usable_theme_coverage")

        if theme_count < 3:
            warnings.append("low_theme_count")
        if excerpt_theme_ratio < 0.75:
            warnings.append("sparse_excerpt_coverage")
        if average_excerpt_chars and average_excerpt_chars < 90:
            warnings.append("short_average_excerpts")
        source_matches_filename, conflicting_institution = self._source_matches_filename(
            source,
            file_name,
        )
        if source and not source_matches_filename:
            warnings.append("source_filename_mismatch")
            if conflicting_institution:
                blocking_issues.append("source_filename_conflict")

        score = 0.0
        score += 0.20 if len(full_text.strip()) >= max(self.settings.min_full_text_chars, 1500) else 0.10
        score += 0.15 if document.ready_for_analysis else 0.0
        score += min(0.25, usable_theme_ratio * 0.25)
        score += min(0.15, excerpt_theme_ratio * 0.15)
        score += min(0.10, non_empty_label_ratio * 0.10)
        if average_excerpt_chars >= 120:
            score += 0.10
        elif average_excerpt_chars >= 60:
            score += 0.05
        if source and source.lower() != "unknown":
            score += 0.05
        score = round(score, 3)

        if score < self.settings.min_quality_score:
            blocking_issues.append("quality_score_below_threshold")

        metrics = {
            "theme_count": theme_count,
            "usable_theme_count": usable_theme_count,
            "usable_theme_ratio": round(usable_theme_ratio, 3),
            "excerpt_theme_ratio": round(excerpt_theme_ratio, 3),
            "average_excerpt_chars": round(average_excerpt_chars, 1),
            "full_text_chars": len(full_text.strip()),
            "source": source or "Unknown",
        }
        return DocumentQualityReport(
            score=score,
            blocking_issues=blocking_issues,
            warnings=warnings,
            metrics=metrics,
        )

    @staticmethod
    def to_json(report: DocumentQualityReport) -> str:
        return json.dumps(
            {
                "score": report.score,
                "blocking_issues": report.blocking_issues,
                "warnings": report.warnings,
                "metrics": report.metrics,
            },
            sort_keys=True,
        )

    @staticmethod
    def _source_matches_filename(source: str, file_name: str) -> tuple[bool, bool]:
        normalized_source = {
            token
            for token in re.split(r"[^a-z0-9]+", source.lower())
            if len(token) >= 2
        }
        normalized_name = {
            token
            for token in re.split(r"[^a-z0-9]+", file_name.lower())
            if len(token) >= 2
        }
        if not normalized_source:
            return False, False

        alias_tokens = set(normalized_source)
        for key, aliases in KNOWN_SOURCE_ALIASES.items():
            if key in source.lower():
                alias_tokens |= aliases

        if alias_tokens & normalized_name:
            return True, False

        conflicting_institution = False
        source_lower = source.lower()
        for key, aliases in KNOWN_SOURCE_ALIASES.items():
            if key in source_lower:
                continue
            if aliases & normalized_name:
                conflicting_institution = True
                break
        return False, conflicting_institution
