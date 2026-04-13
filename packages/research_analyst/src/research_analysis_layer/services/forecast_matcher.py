"""Forecast candidate matching and upload preparation."""

from __future__ import annotations

from dataclasses import replace

from research_analysis_layer.models import ForecastCandidateDraft, ForecastCandidateRecord


class ForecastMatcher:
    """Match forecast candidates to canonical economic event rows."""

    _EVENT_NAME_ALIASES = {
        "us_nfp": ("Employment Situation", "Change in Nonfarm Payrolls", "Nonfarm Payrolls"),
        "us_private_payrolls": ("Employment Situation", "Change in Private Payrolls", "Private Payrolls"),
        "us_unemployment_rate": ("Employment Situation", "Unemployment Rate"),
        "us_average_hourly_earnings_mom": (
            "Employment Situation",
            "Average Hourly Earnings m/m",
            "Average Hourly Earnings",
        ),
        "us_average_weekly_hours": (
            "Employment Situation",
            "Average Weekly Hours All Employees",
            "Average Weekly Hours",
        ),
        "us_labor_force_participation_rate": (
            "Employment Situation",
            "Labor Force Participation Rate",
            "Labor Force Participation",
        ),
        "us_adp_employment_change": (
            "ADP National Employment Report",
            "ADP Employment Change",
            "ADP Employment Weekly",
            "ADP",
        ),
        "us_retail_sales_headline_mom": (
            "Advance Monthly Sales for Retail and Food Services",
            "Retail Sales Advance m/m",
            "Retail Sales",
        ),
        "us_retail_sales_ex_auto_mom": (
            "Advance Monthly Sales for Retail and Food Services",
            "Retail Sales Ex Auto m/m",
            "Retail Sales Ex-Auto",
        ),
        "us_retail_sales_control_group_mom": (
            "Advance Monthly Sales for Retail and Food Services",
            "Retail Sales Control Group",
        ),
        "us_ism_manufacturing": (
            "ISM Manufacturing Report On Business",
            "Manufacturing ISM Report On Business",
            "ISM Manufacturing",
            "ISM Manufacturing PMI",
        ),
        "us_cpi_core_mom": ("Core CPI m/m", "Core CPI"),
        "us_cpi_mom": ("CPI m/m", "CPI"),
    }

    def match_candidate(
        self,
        candidate: ForecastCandidateDraft,
        client,
    ) -> ForecastCandidateDraft:
        if not candidate.release_date:
            return replace(
                candidate,
                match_status="ambiguous",
                review_status="needs_human_review",
                review_notes="missing_release_date",
            )
        try:
            search_fn = getattr(client, "search_calendar_matches", None)
            if search_fn is None:
                search_fn = getattr(client, "search_economic_events")
            event_rows = search_fn(
                release_date=candidate.release_date,
                country=candidate.country,
                limit=50,
            )
        except Exception:
            return replace(
                candidate,
                match_status="ambiguous",
                review_status="needs_human_review",
                review_notes="event_lookup_error",
            )
        matched_rows = self._resolve_matches(candidate, event_rows)
        if len(matched_rows) == 1:
            matched_row = matched_rows[0]
            matched_id = matched_row.get("id")
            match_source = str(getattr(client, "match_source", "economic_events") or "economic_events")
            source_name = str(
                matched_row.get("calendar_source")
                or getattr(client, "source_name", "")
                or match_source
            )
            return replace(
                candidate,
                match_status="matched_exact",
                matched_economic_event_id=(
                    str(matched_id)
                    if match_source != "release_dates" and matched_id is not None
                    else None
                ),
                matched_calendar_release_id=(
                    str(matched_row.get("calendar_release_id") or matched_id)
                    if matched_id is not None
                    else None
                ),
                matched_calendar_source=source_name,
                review_status=self._review_status(candidate, matched=True),
            )
        if not matched_rows:
            return replace(
                candidate,
                match_status="no_event_found",
                review_status=self._review_status(candidate, matched=False),
            )
        return replace(
            candidate,
            match_status="ambiguous",
            review_status="needs_human_review",
            review_notes="multiple_event_matches",
        )

    def _resolve_matches(
        self,
        candidate: ForecastCandidateDraft,
        event_rows: list[dict],
    ) -> list[dict]:
        if not event_rows:
            return []
        aliases = self._aliases_for_candidate(candidate)
        scored_rows: list[tuple[int, int, dict]] = []
        for row in event_rows:
            score = self._match_score(
                aliases=aliases,
                row_event_name=str(row.get("event_name") or ""),
                candidate_period=candidate.period_text,
                row_period=row.get("period"),
            )
            if score[0] > 0:
                scored_rows.append((score[0], score[1], row))
        if not scored_rows:
            return []
        scored_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score = scored_rows[0][:2]
        return [row for primary, secondary, row in scored_rows if (primary, secondary) == best_score]

    def _aliases_for_candidate(self, candidate: ForecastCandidateDraft) -> tuple[str, ...]:
        aliases = list(self._EVENT_NAME_ALIASES.get(candidate.indicator_key, ()))
        if candidate.event_name and candidate.event_name not in aliases:
            aliases.append(candidate.event_name)
        return tuple(aliases)

    def _match_score(
        self,
        *,
        aliases: tuple[str, ...],
        row_event_name: str,
        candidate_period: str | None,
        row_period: object | None,
    ) -> tuple[int, int]:
        normalized_row = self._normalize(row_event_name)
        name_score = 0
        for alias in aliases:
            normalized_alias = self._normalize(alias)
            if not normalized_alias:
                continue
            if normalized_row == normalized_alias:
                name_score = max(name_score, 3)
            elif normalized_row.startswith(normalized_alias) or normalized_alias.startswith(normalized_row):
                name_score = max(name_score, 2)
            elif normalized_alias in normalized_row or normalized_row in normalized_alias:
                name_score = max(name_score, 1)
        if name_score == 0:
            return (0, 0)
        period_score = 0
        normalized_candidate_period = self._normalize_period(candidate_period)
        normalized_row_period = self._normalize_period(str(row_period or ""))
        if normalized_candidate_period and normalized_row_period == normalized_candidate_period:
            period_score = 1
        return (name_score, period_score)

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(
            "".join(char.lower() if char.isalnum() else " " for char in value).split()
        )

    @classmethod
    def _normalize_period(cls, value: str | None) -> str:
        if not value:
            return ""
        parts = [part for part in cls._normalize(value).split() if part]
        if not parts:
            return ""
        month = parts[0][:3]
        return month

    @staticmethod
    def to_upload_payload(candidate: ForecastCandidateRecord) -> dict[str, object]:
        payload = {
            "parsed_research_id": candidate.research_id,
            "source": candidate.source,
            "source_date": candidate.source_date,
            "document_name": candidate.document_name,
            "document_link": candidate.document_link,
            "document_hash": candidate.document_hash,
            "indicator_key": candidate.indicator_key,
            "event_name": candidate.event_name,
            "country": candidate.country,
            "period": candidate.period_text,
            "release_date": candidate.release_date,
            "forecast_type": candidate.forecast_type,
            "forecast_value_numeric": candidate.forecast_value_numeric,
            "forecast_value_low": candidate.forecast_value_low,
            "forecast_value_high": candidate.forecast_value_high,
            "forecast_value_text": candidate.forecast_value_text,
            "forecast_unit": candidate.forecast_unit,
            "qualifier_text": candidate.qualifier_text,
            "extraction_confidence": candidate.extraction_confidence,
            "evidence_text": candidate.evidence_text,
            "review_status": "uploaded",
        }
        if (
            candidate.matched_economic_event_id is None
            and candidate.matched_calendar_release_id is not None
        ):
            payload["calendar_source"] = candidate.matched_calendar_source
            payload["external_release_id"] = candidate.matched_calendar_release_id
        else:
            payload["economic_event_id"] = candidate.matched_economic_event_id
        return payload

    @staticmethod
    def _review_status(candidate: ForecastCandidateDraft, *, matched: bool) -> str:
        if candidate.forecast_type == "point" and candidate.forecast_value_numeric is not None:
            if matched or candidate.release_date:
                return "approved"
        return "needs_human_review"
