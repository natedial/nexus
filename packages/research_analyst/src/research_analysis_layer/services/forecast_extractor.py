"""Deterministic forecast candidate extraction."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import re

from research_analysis_layer.models import ForecastCandidateDraft, ForecastExtractionSource


class ForecastExtractor:
    """Extract normalized economic forecast candidates from local assertions."""

    _MONTH_LOOKUP = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    def extract(self, source: ForecastExtractionSource) -> list[ForecastCandidateDraft]:
        text = " ".join(
            part.strip()
            for part in [source.summary_text, source.assertion_text, source.evidence_text]
            if part and part.strip()
        )
        indicator = self._detect_indicator(text)
        if indicator is None:
            return []

        release_date = self._extract_release_date(text, source.source_date)
        period_text = self._extract_period_text(text, source.source_date)
        if release_date is None and period_text is None:
            return []
        forecast = self._extract_forecast_value(text, indicator["indicator_key"])
        if forecast is None:
            forecast = {
                "forecast_type": "directional",
                "forecast_value_numeric": None,
                "forecast_value_low": None,
                "forecast_value_high": None,
                "forecast_value_text": self._extract_directional_text(text),
                "forecast_unit": None,
            }

        candidate = ForecastCandidateDraft(
            research_id=source.research_id,
            file_id=source.file_id,
            document_hash=source.document_hash,
            source=source.source,
            source_date=source.source_date,
            document_name=source.document_name,
            document_link=source.document_link,
            chunk_order=source.chunk_order,
            assertion_order=source.assertion_order,
            assertion_text=source.assertion_text,
            summary_text=source.summary_text,
            evidence_text=source.evidence_text,
            indicator_key=indicator["indicator_key"],
            event_name=indicator["event_name"],
            country=indicator["country"],
            period_text=period_text,
            release_date=release_date,
            forecast_type=forecast["forecast_type"],
            forecast_value_numeric=forecast["forecast_value_numeric"],
            forecast_value_low=forecast["forecast_value_low"],
            forecast_value_high=forecast["forecast_value_high"],
            forecast_value_text=forecast["forecast_value_text"],
            forecast_unit=forecast["forecast_unit"],
            qualifier_text=source.qualifier_text,
            extraction_confidence=source.extraction_confidence,
            created_run_id=source.created_run_id,
        )
        if (
            candidate.forecast_type == "point"
            and candidate.forecast_value_numeric is not None
            and candidate.release_date is not None
        ):
            candidate = replace(candidate, review_status="approved")
        return [candidate]

    @staticmethod
    def _detect_indicator(text: str) -> dict[str, str] | None:
        lowered = text.lower()
        if re.search(r"\b(nonfarm payrolls?|nfp)\b", lowered) or (
            "payroll" in lowered and "jobs" in lowered
        ):
            return {
                "indicator_key": "us_nfp",
                "event_name": "Nonfarm Payrolls",
                "country": "US",
            }
        if "unemployment rate" in lowered:
            return {
                "indicator_key": "us_unemployment_rate",
                "event_name": "Unemployment Rate",
                "country": "US",
            }
        if "core cpi" in lowered and ForecastExtractor._contains_yoy(lowered):
            return {
                "indicator_key": "us_cpi_core_yoy",
                "event_name": "Core CPI",
                "country": "US",
            }
        if "core cpi" in lowered:
            return {
                "indicator_key": "us_cpi_core_mom",
                "event_name": "Core CPI",
                "country": "US",
            }
        if "cpi" in lowered and ForecastExtractor._contains_yoy(lowered):
            return {
                "indicator_key": "us_cpi_headline_yoy",
                "event_name": "CPI",
                "country": "US",
            }
        if "cpi" in lowered:
            return {
                "indicator_key": "us_cpi_headline_mom",
                "event_name": "CPI",
                "country": "US",
            }
        return None

    @staticmethod
    def _contains_mom(text: str) -> bool:
        return any(token in text for token in ["mom", "m/m", "month over month"])

    @staticmethod
    def _contains_yoy(text: str) -> bool:
        return any(token in text for token in ["yoy", "y/y", "year over year"])

    def _extract_release_date(self, text: str, source_date: str | None) -> str | None:
        if not source_date:
            return None
        try:
            source_day = date.fromisoformat(source_date)
        except ValueError:
            return None
        match = re.search(
            r"\b(?:for|on|ahead of|into)\s+"
            r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+"
            r"(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        month = self._MONTH_LOOKUP[match.group("month").lower()]
        day = int(match.group("day"))
        year = int(match.group("year") or source_day.year)
        try:
            resolved = date(year, month, day)
        except ValueError:
            return None
        if match.group("year") is None and resolved < source_day:
            try:
                resolved = date(year + 1, month, day)
            except ValueError:
                return None
        return resolved.isoformat()

    def _extract_period_text(self, text: str, source_date: str | None) -> str | None:
        match = re.search(
            r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
            r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|"
            r"nov(?:ember)?|dec(?:ember)?)\s+"
            r"(?:(?P<year>\d{4})\s+)?"
            r"(?:nfp|nonfarm payrolls?|payrolls|cpi|inflation|retail sales|unemployment)\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        month_name = match.group("month").title()
        year = match.group("year")
        if year:
            return f"{month_name} {year}"
        if source_date:
            try:
                return f"{month_name} {date.fromisoformat(source_date).year}"
            except ValueError:
                return month_name
        return month_name

    def _extract_forecast_value(
        self,
        text: str,
        indicator_key: str,
    ) -> dict[str, str | float | None] | None:
        if indicator_key == "us_nfp":
            range_match = re.search(
                r"(?P<first>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<first_suffix>k|m)?"
                r"\s*(?:jobs|payrolls?)?\s*(?:to|-)\s*"
                r"(?P<second>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<second_suffix>k|m)?"
                r"\s*(?P<unit>jobs|payrolls?)\b",
                text,
                re.IGNORECASE,
            )
            if range_match:
                low = self._scale_number(range_match.group("first"), range_match.group("first_suffix"))
                high = self._scale_number(range_match.group("second"), range_match.group("second_suffix"))
                return {
                    "forecast_type": "range",
                    "forecast_value_numeric": None,
                    "forecast_value_low": low,
                    "forecast_value_high": high,
                    "forecast_value_text": range_match.group(0).strip(),
                    "forecast_unit": "jobs",
                }
            point_match = re.search(
                r"(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<suffix>k|m)?\s*(?P<unit>jobs|payrolls?)\b",
                text,
                re.IGNORECASE,
            )
            if point_match:
                return {
                    "forecast_type": "point",
                    "forecast_value_numeric": self._scale_number(
                        point_match.group("value"),
                        point_match.group("suffix"),
                    ),
                    "forecast_value_low": None,
                    "forecast_value_high": None,
                    "forecast_value_text": point_match.group(0).strip(),
                    "forecast_unit": "jobs",
                }
            estimated_payrolls = re.search(
                r"(?:estimate|expect|forecast)[^.]{0,80}?"
                r"(?:nonfarm payrolls?|nfp|payrolls?)[^.]{0,40}?"
                r"(?:rose|rise|grow(?:th)?|print|come in|at|to|of|by)?\s*"
                r"(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<suffix>k|m)?\b",
                text,
                re.IGNORECASE,
            )
            if estimated_payrolls:
                return {
                    "forecast_type": "point",
                    "forecast_value_numeric": self._scale_number(
                        estimated_payrolls.group("value"),
                        estimated_payrolls.group("suffix"),
                    ),
                    "forecast_value_low": None,
                    "forecast_value_high": None,
                    "forecast_value_text": estimated_payrolls.group(0).strip(),
                    "forecast_unit": "jobs",
                }
            payrolls_at = re.search(
                r"(?:nonfarm payrolls?|nfp|payrolls?)[^.]{0,40}?"
                r"(?:at|to|of|by)\s*(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<suffix>k|m)?\b",
                text,
                re.IGNORECASE,
            )
            if payrolls_at:
                return {
                    "forecast_type": "point",
                    "forecast_value_numeric": self._scale_number(
                        payrolls_at.group("value"),
                        payrolls_at.group("suffix"),
                    ),
                    "forecast_value_low": None,
                    "forecast_value_high": None,
                    "forecast_value_text": payrolls_at.group(0).strip(),
                    "forecast_unit": "jobs",
                }

        if indicator_key in {
            "us_unemployment_rate",
            "us_cpi_core_yoy",
            "us_cpi_core_mom",
            "us_cpi_headline_yoy",
            "us_cpi_headline_mom",
        }:
            if indicator_key == "us_unemployment_rate":
                unemployment_match = re.search(
                    r"unemployment rate[^.%]{0,40}?(?:at|to|of|was|around)?\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*%",
                    text,
                    re.IGNORECASE,
                )
                if unemployment_match:
                    return {
                        "forecast_type": "point",
                        "forecast_value_numeric": float(unemployment_match.group("value")),
                        "forecast_value_low": None,
                        "forecast_value_high": None,
                        "forecast_value_text": unemployment_match.group(0).strip(),
                        "forecast_unit": "%",
                    }
            range_match = re.search(
                r"(?P<first>[+-]?\d+(?:\.\d+)?)\s*%\s*(?:to|-)\s*"
                r"(?P<second>[+-]?\d+(?:\.\d+)?)\s*%",
                text,
                re.IGNORECASE,
            )
            if range_match:
                return {
                    "forecast_type": "range",
                    "forecast_value_numeric": None,
                    "forecast_value_low": float(range_match.group("first")),
                    "forecast_value_high": float(range_match.group("second")),
                    "forecast_value_text": range_match.group(0).strip(),
                    "forecast_unit": "%",
                }
            if indicator_key in {"us_cpi_core_mom", "us_cpi_headline_mom"}:
                cpi_mom_match = re.search(
                    r"(?:expect|forecast|estimate)[^.]{0,50}?"
                    r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*%\s+"
                    r"(?:increase|rise|gain)[^.]{0,60}?"
                    r"(?:core\s+)?cpi",
                    text,
                    re.IGNORECASE,
                )
                if cpi_mom_match:
                    return {
                        "forecast_type": "point",
                        "forecast_value_numeric": float(cpi_mom_match.group("value")),
                        "forecast_value_low": None,
                        "forecast_value_high": None,
                        "forecast_value_text": cpi_mom_match.group(0).strip(),
                        "forecast_unit": "%",
                    }
            point_match = re.search(
                r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*%",
                text,
                re.IGNORECASE,
            )
            if point_match:
                return {
                    "forecast_type": "point",
                    "forecast_value_numeric": float(point_match.group("value")),
                    "forecast_value_low": None,
                    "forecast_value_high": None,
                    "forecast_value_text": point_match.group(0).strip(),
                    "forecast_unit": "%",
                }
        return None

    @staticmethod
    def _scale_number(value: str, suffix: str | None) -> float:
        number = float(value.replace(",", ""))
        if suffix is None:
            return number
        lowered = suffix.lower()
        if lowered == "k":
            return number * 1000
        if lowered == "m":
            return number * 1_000_000
        return number

    @staticmethod
    def _extract_directional_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if normalized:
            return normalized[:240]
        return "directional forecast"
