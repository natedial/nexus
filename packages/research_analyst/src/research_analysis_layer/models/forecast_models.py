"""Forecast extraction models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ForecastExtractionSource:
    """Local forecast assertion plus supporting provenance."""

    research_id: int
    file_id: str | None
    document_hash: str | None
    source: str | None
    source_date: str | None
    document_name: str | None
    document_link: str | None
    chunk_order: int
    assertion_order: int
    assertion_text: str
    summary_text: str
    evidence_text: str
    qualifier_text: str | None
    extraction_confidence: str
    created_run_id: int


@dataclass(slots=True)
class ForecastCandidateDraft:
    """Normalized local forecast candidate before external upload."""

    research_id: int
    file_id: str | None
    document_hash: str | None
    source: str | None
    source_date: str | None
    document_name: str | None
    document_link: str | None
    chunk_order: int
    assertion_order: int
    assertion_text: str
    summary_text: str
    evidence_text: str
    indicator_key: str
    event_name: str
    country: str | None
    period_text: str | None
    release_date: str | None
    forecast_type: str
    forecast_value_numeric: float | None
    forecast_value_low: float | None
    forecast_value_high: float | None
    forecast_value_text: str
    forecast_unit: str | None
    qualifier_text: str | None
    extraction_confidence: str
    match_status: str = "unmatched"
    matched_economic_event_id: str | None = None
    matched_calendar_release_id: str | None = None
    matched_calendar_source: str | None = None
    review_status: str = "pending"
    review_notes: str | None = None
    upload_status: str = "not_uploaded"
    created_run_id: int | None = None


@dataclass(slots=True)
class ForecastCandidateRecord(ForecastCandidateDraft):
    """Persisted local forecast candidate."""

    id: int = 0
    uploaded_at: str | None = None
