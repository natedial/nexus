"""Structured forecast extraction directly from parser full_text."""

from __future__ import annotations

from datetime import date
import re

from research_analysis_layer.models import ForecastCandidateDraft, ParsedDocument
from research_analysis_layer.parsed_payload import full_text as payload_full_text


class RawForecastExtractor:
    """Mine calendar-style macro forecasts from raw parsed document text."""

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

    _SECTION_LAYOUT = {
        "employment": 100,
        "adp": 200,
        "retail_sales": 300,
        "ism_manufacturing": 400,
    }
    _KNOWN_SECTION_NAMES = (
        "Employment",
        "ADP",
        "Retail Sales",
        "ISM Manufacturing",
    )

    def extract(
        self,
        *,
        document: ParsedDocument,
        file_id: str | None,
        created_run_id: int | None,
    ) -> list[ForecastCandidateDraft]:
        parsed_data = document.parsed_data if isinstance(document.parsed_data, dict) else {}
        raw_text = payload_full_text(parsed_data)
        if not raw_text.strip():
            return []

        candidates: list[ForecastCandidateDraft] = []
        source_year = self._source_year(document.source_date)

        employment_section = self._find_section(raw_text, "Employment")
        if employment_section:
            release_date = self._extract_release_date(employment_section["header"], source_year)
            period_text = self._extract_employment_period_text(
                f"{employment_section['header']}\n{employment_section['body']}",
                source_year,
            )
            candidates.extend(
                self._extract_employment_candidates(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    body=employment_section["body"],
                    header=employment_section["header"],
                    release_date=release_date,
                    period_text=period_text,
                )
            )

        adp_section = self._find_section(raw_text, "ADP")
        if adp_section:
            release_date = self._extract_release_date(adp_section["header"], source_year)
            period_text = self._extract_period_text(adp_section["body"], source_year)
            adp_candidate = self._extract_single_candidate(
                document=document,
                file_id=file_id,
                created_run_id=created_run_id,
                chunk_order=self._SECTION_LAYOUT["adp"],
                assertion_order=1,
                header=adp_section["header"],
                body=adp_section["body"],
                indicator_key="us_adp_employment_change",
                event_name="ADP Employment Change",
                country="US",
                release_date=release_date,
                period_text=period_text,
                pattern=r"(?:ms\s+forecast|forecast|expect|tracking)\s*[:=]?\s*(?P<value>[+-]?\d+(?:\.\d+)?)\s*(?P<suffix>k|m)\b",
                forecast_unit="jobs",
            )
            if adp_candidate is not None:
                candidates.append(adp_candidate)

        retail_section = self._find_section(raw_text, "Retail Sales")
        if retail_section:
            release_date = self._extract_release_date(retail_section["header"], source_year)
            period_text = self._extract_period_text(retail_section["header"], source_year)
            retail_candidates = [
                ("us_retail_sales_headline_mom", "Retail Sales", 1, r"Headline\s*[:=]\s*(?P<value>[+-]?\d+(?:\.\d+)?)%"),
                ("us_retail_sales_ex_auto_mom", "Retail Sales Ex-Auto", 2, r"Ex-auto\s*[:=]\s*(?P<value>[+-]?\d+(?:\.\d+)?)%"),
                ("us_retail_sales_control_group_mom", "Retail Sales Control Group", 3, r"Control group\s*[:=]\s*(?P<value>[+-]?\d+(?:\.\d+)?)%"),
            ]
            for indicator_key, event_name, assertion_order, pattern in retail_candidates:
                candidate = self._extract_single_candidate(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    chunk_order=self._SECTION_LAYOUT["retail_sales"],
                    assertion_order=assertion_order,
                    header=retail_section["header"],
                    body=retail_section["body"],
                    indicator_key=indicator_key,
                    event_name=event_name,
                    country="US",
                    release_date=release_date,
                    period_text=period_text,
                    pattern=pattern,
                    forecast_unit="%",
                )
                if candidate is not None:
                    candidates.append(candidate)

        ism_section = self._find_section(raw_text, "ISM Manufacturing")
        if ism_section:
            release_date = self._extract_release_date(ism_section["header"], source_year)
            period_text = self._extract_period_text(ism_section["header"], source_year)
            ism_candidate = self._extract_single_candidate(
                document=document,
                file_id=file_id,
                created_run_id=created_run_id,
                chunk_order=self._SECTION_LAYOUT["ism_manufacturing"],
                assertion_order=1,
                header=ism_section["header"],
                body=ism_section["body"],
                indicator_key="us_ism_manufacturing",
                event_name="ISM Manufacturing",
                country="US",
                release_date=release_date,
                period_text=period_text,
                pattern=r"(?:tracking|forecast|expect)\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)\b",
                forecast_unit="index",
            )
            if ism_candidate is not None:
                candidates.append(ism_candidate)

        table_candidates = self._extract_table_row_candidates(
            text=raw_text,
            document=document,
            file_id=file_id,
            created_run_id=created_run_id,
            source_year=source_year,
        )
        candidate_map = {candidate.indicator_key: candidate for candidate in candidates}
        for table_candidate in table_candidates:
            existing_candidate = candidate_map.get(table_candidate.indicator_key)
            if existing_candidate is None:
                candidates.append(table_candidate)
                candidate_map[table_candidate.indicator_key] = table_candidate
                continue
            self._merge_candidate_metadata(existing_candidate, table_candidate)

        return candidates

    def _extract_employment_candidates(
        self,
        *,
        document: ParsedDocument,
        file_id: str | None,
        created_run_id: int | None,
        body: str,
        header: str,
        release_date: str | None,
        period_text: str | None,
    ) -> list[ForecastCandidateDraft]:
        candidates: list[ForecastCandidateDraft] = []
        sentence = f"{header}\n{body}"

        payroll_match = re.search(
            r"headline(?:\s+and|\s*,)?\s+private(?:\s+nonfarm)?\s+payrolls?\s+(?:to\s+)?(?:rise|rose|increase|print)\s+by\s+"
            r"(?P<headline>[+-]?\d+(?:\.\d+)?)\s*(?P<headline_suffix>k|m)\s+and\s+"
            r"(?P<private>[+-]?\d+(?:\.\d+)?)\s*(?P<private_suffix>k|m)",
            sentence,
            re.IGNORECASE,
        )
        if payroll_match is None:
            payroll_match = re.search(
                r"headline(?:\s+nfp)?\s*[:=]\s*(?P<headline>[+-]?\d+(?:\.\d+)?)\s*(?P<headline_suffix>k|m).*?"
                r"private(?:\s+payrolls?)?\s*[:=]\s*(?P<private>[+-]?\d+(?:\.\d+)?)\s*(?P<private_suffix>k|m)",
                sentence,
                re.IGNORECASE | re.DOTALL,
            )
        if payroll_match:
            candidates.append(
                self._build_candidate(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    chunk_order=self._SECTION_LAYOUT["employment"],
                    assertion_order=1,
                    indicator_key="us_nfp",
                    event_name="Nonfarm Payrolls",
                    country="US",
                    release_date=release_date,
                    period_text=period_text,
                    summary_text="Employment forecast",
                    assertion_text=payroll_match.group(0).strip(),
                    evidence_text=sentence.strip(),
                    forecast_type="point",
                    forecast_value_numeric=self._scale_number(
                        payroll_match.group("headline"),
                        payroll_match.group("headline_suffix"),
                    ),
                    forecast_value_text=f"{payroll_match.group('headline')}{payroll_match.group('headline_suffix')} jobs",
                    forecast_unit="jobs",
                )
            )
            candidates.append(
                self._build_candidate(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    chunk_order=self._SECTION_LAYOUT["employment"],
                    assertion_order=2,
                    indicator_key="us_private_payrolls",
                    event_name="Private Payrolls",
                    country="US",
                    release_date=release_date,
                    period_text=period_text,
                    summary_text="Employment forecast",
                    assertion_text=payroll_match.group(0).strip(),
                    evidence_text=sentence.strip(),
                    forecast_type="point",
                    forecast_value_numeric=self._scale_number(
                        payroll_match.group("private"),
                        payroll_match.group("private_suffix"),
                    ),
                    forecast_value_text=f"{payroll_match.group('private')}{payroll_match.group('private_suffix')} jobs",
                    forecast_unit="jobs",
                )
            )

        series_patterns = [
            (
                "us_unemployment_rate",
                "Unemployment Rate",
                3,
                r"unemployment rate(?:\s*[:=]\s*|\s+(?:to\s+)?(?:hold steady at|remain at|be|print at|rise to|fall to)\s+)(?P<value>\d+(?:\.\d+)?)%",
                "%",
            ),
            (
                "us_average_hourly_earnings_mom",
                "Average Hourly Earnings",
                4,
                r"average hourly earnings\s*[:=]?\s*(?P<value>[+-]?\d+(?:\.\d+)?)%\s*(?:m/m|mom)",
                "%",
            ),
            (
                "us_labor_force_participation_rate",
                "Labor Force Participation Rate",
                5,
                r"labor force participation\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)%",
                "%",
            ),
            (
                "us_average_weekly_hours",
                "Average Weekly Hours",
                6,
                r"(?:avg|average)\s+weekly hours\s*[:=]?\s*(?P<value>\d+(?:\.\d+)?)\b",
                "hours",
            ),
        ]
        for indicator_key, event_name, assertion_order, pattern, forecast_unit in series_patterns:
            match = re.search(pattern, sentence, re.IGNORECASE)
            if not match:
                continue
            candidates.append(
                self._build_candidate(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    chunk_order=self._SECTION_LAYOUT["employment"],
                    assertion_order=assertion_order,
                    indicator_key=indicator_key,
                    event_name=event_name,
                    country="US",
                    release_date=release_date,
                    period_text=period_text,
                    summary_text="Employment forecast",
                    assertion_text=match.group(0).strip(),
                    evidence_text=sentence.strip(),
                    forecast_type="point",
                    forecast_value_numeric=float(match.group("value")),
                    forecast_value_text=match.group("value"),
                    forecast_unit=forecast_unit,
                )
            )
        return candidates

    def _extract_single_candidate(
        self,
        *,
        document: ParsedDocument,
        file_id: str | None,
        created_run_id: int | None,
        chunk_order: int,
        assertion_order: int,
        header: str,
        body: str,
        indicator_key: str,
        event_name: str,
        country: str,
        release_date: str | None,
        period_text: str | None,
        pattern: str,
        forecast_unit: str,
    ) -> ForecastCandidateDraft | None:
        sentence = f"{header}\n{body}".strip()
        match = re.search(pattern, sentence, re.IGNORECASE)
        if not match:
            return None
        value = match.group("value")
        suffix = match.groupdict().get("suffix")
        numeric = self._scale_number(value, suffix) if suffix else float(value)
        return self._build_candidate(
            document=document,
            file_id=file_id,
            created_run_id=created_run_id,
            chunk_order=chunk_order,
            assertion_order=assertion_order,
            indicator_key=indicator_key,
            event_name=event_name,
            country=country,
            release_date=release_date,
            period_text=period_text,
            summary_text=header.strip(),
            assertion_text=match.group(0).strip(),
            evidence_text=sentence,
            forecast_type="point",
            forecast_value_numeric=numeric,
            forecast_value_text=f"{value}{suffix or ''}",
            forecast_unit=forecast_unit,
        )

    def _build_candidate(
        self,
        *,
        document: ParsedDocument,
        file_id: str | None,
        created_run_id: int | None,
        chunk_order: int,
        assertion_order: int,
        indicator_key: str,
        event_name: str,
        country: str,
        release_date: str | None,
        period_text: str | None,
        summary_text: str,
        assertion_text: str,
        evidence_text: str,
        forecast_type: str,
        forecast_value_numeric: float | None,
        forecast_value_text: str,
        forecast_unit: str | None,
    ) -> ForecastCandidateDraft:
        review_status = "approved" if forecast_value_numeric is not None and release_date is not None else "needs_human_review"
        return ForecastCandidateDraft(
            research_id=document.id,
            file_id=file_id,
            document_hash=document.document_hash,
            source=document.source,
            source_date=document.source_date,
            document_name=document.document_name,
            document_link=document.document_link,
            chunk_order=chunk_order,
            assertion_order=assertion_order,
            assertion_text=assertion_text,
            summary_text=summary_text,
            evidence_text=evidence_text,
            indicator_key=indicator_key,
            event_name=event_name,
            country=country,
            period_text=period_text,
            release_date=release_date,
            forecast_type=forecast_type,
            forecast_value_numeric=forecast_value_numeric,
            forecast_value_low=None,
            forecast_value_high=None,
            forecast_value_text=forecast_value_text,
            forecast_unit=forecast_unit,
            qualifier_text=None,
            extraction_confidence="high" if forecast_value_numeric is not None else "medium",
            review_status=review_status,
            created_run_id=created_run_id,
        )

    def _extract_table_row_candidates(
        self,
        *,
        text: str,
        document: ParsedDocument,
        file_id: str | None,
        created_run_id: int | None,
        source_year: int | None,
    ) -> list[ForecastCandidateDraft]:
        month_pattern = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
        row_specs = [
            (r"Change in Nonfarm Payrolls", "us_nfp", "Nonfarm Payrolls", "jobs_thousands", 501),
            (r"Change in Private Payrolls", "us_private_payrolls", "Private Payrolls", "jobs_thousands", 502),
            (r"Average Hourly Earnings m/m", "us_average_hourly_earnings_mom", "Average Hourly Earnings", "percent", 503),
            (r"Average Weekly Hours All Employees", "us_average_weekly_hours", "Average Weekly Hours", "hours", 504),
            (r"Unemployment Rate", "us_unemployment_rate", "Unemployment Rate", "percent", 505),
            (r"Labor Force Participation Rate", "us_labor_force_participation_rate", "Labor Force Participation Rate", "percent", 506),
            (r"(?:Retail Sales Advance m/m|Retail Sales Headline m/m)", "us_retail_sales_headline_mom", "Retail Sales", "percent", 507),
            (r"Retail Sales Ex Auto m/m", "us_retail_sales_ex_auto_mom", "Retail Sales Ex-Auto", "percent", 508),
            (r"Retail Sales Control Group", "us_retail_sales_control_group_mom", "Retail Sales Control Group", "percent", 509),
            (r"ISM Manufacturing", "us_ism_manufacturing", "ISM Manufacturing", "index", 510),
            (r"ADP Employment Change", "us_adp_employment_change", "ADP Employment Change", "jobs_thousands", 511),
        ]
        candidates: list[ForecastCandidateDraft] = []
        for label_pattern, indicator_key, event_name, value_kind, assertion_order in row_specs:
            match = re.search(
                rf"(?P<label>{label_pattern})\s+(?P<period>{month_pattern})\s+(?:[FP]\s+)?(?P<value>[+-]?\d+(?:\.\d+)?)\b",
                text,
                re.IGNORECASE,
            )
            if not match:
                continue
            raw_value = float(match.group("value"))
            forecast_value_numeric = raw_value * 1000 if value_kind == "jobs_thousands" else raw_value
            period_text = f"{match.group('period').title()} {source_year}" if source_year is not None else match.group("period").title()
            release_date = self._find_schedule_release_date(text, match.start(), source_year)
            forecast_unit = (
                "jobs" if value_kind == "jobs_thousands" else
                "%" if value_kind == "percent" else
                "hours" if value_kind == "hours" else
                "index"
            )
            snippet_start = max(0, match.start() - 140)
            snippet_end = min(len(text), match.end() + 220)
            snippet = text[snippet_start:snippet_end].strip()
            candidates.append(
                self._build_candidate(
                    document=document,
                    file_id=file_id,
                    created_run_id=created_run_id,
                    chunk_order=500,
                    assertion_order=assertion_order,
                    indicator_key=indicator_key,
                    event_name=event_name,
                    country="US",
                    release_date=release_date,
                    period_text=period_text,
                    summary_text=event_name,
                    assertion_text=match.group(0).strip(),
                    evidence_text=snippet,
                    forecast_type="point",
                    forecast_value_numeric=forecast_value_numeric,
                    forecast_value_text=match.group("value"),
                    forecast_unit=forecast_unit,
                )
            )
        return candidates

    @staticmethod
    def _find_section(text: str, section_name: str) -> dict[str, str] | None:
        header_pattern = re.compile(
            rf"(?P<header>{section_name}\s*(?:\([^)]*\))?\s*:?[^\n]*)",
            re.IGNORECASE,
        )
        header_match = header_pattern.search(text)
        if not header_match:
            return None
        body_start = header_match.end()
        next_header_pattern = re.compile(
            r"\n\s*(Employment|ADP|Retail Sales|ISM Manufacturing)\s*(?:\([^)]*\))?\s*:?",
            re.IGNORECASE,
        )
        next_match = next_header_pattern.search(text, body_start)
        body_end = next_match.start() if next_match else len(text)
        return {
            "header": header_match.group("header").strip(),
            "body": text[body_start:body_end].strip()[:1200],
        }

    def _extract_release_date(self, header_text: str, source_year: int | None) -> str | None:
        if source_year is None:
            return None
        match = re.search(
            r"\((?:[A-Za-z]+\s+)?(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(?P<day>\d{1,2})",
            header_text,
            re.IGNORECASE,
        )
        if not match:
            return None
        month = self._MONTH_LOOKUP[match.group("month").lower()]
        return date(source_year, month, int(match.group("day"))).isoformat()

    def _extract_period_text(self, text: str, source_year: int | None) -> str | None:
        match = re.search(
            r"\b(?:for|—)\s*(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            text,
            re.IGNORECASE,
        )
        if not match:
            return None
        month = match.group("month").title()
        if source_year is None:
            return month
        return f"{month} {source_year}"

    @staticmethod
    def _merge_candidate_metadata(
        candidate: ForecastCandidateDraft,
        supplemental: ForecastCandidateDraft,
    ) -> None:
        if supplemental.release_date and not candidate.release_date:
            candidate.release_date = supplemental.release_date
        if supplemental.period_text and (
            not candidate.period_text
            or (
                supplemental.release_date
                and not RawForecastExtractor._periods_equivalent(
                    candidate.period_text,
                    supplemental.period_text,
                )
            )
        ):
            candidate.period_text = supplemental.period_text
        if candidate.review_status != "approved" and candidate.release_date is not None:
            candidate.review_status = "approved"

    @staticmethod
    def _periods_equivalent(left: str | None, right: str | None) -> bool:
        if not left or not right:
            return False
        left_parts = left.split()
        right_parts = right.split()
        if len(left_parts) != 2 or len(right_parts) != 2:
            return left == right
        left_month, left_year = left_parts
        right_month, right_year = right_parts
        return left_year == right_year and left_month[:3].lower() == right_month[:3].lower()

    def _extract_employment_period_text(self, text: str, source_year: int | None) -> str | None:
        match = re.search(
            r"\bfor\s+(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+employment\b",
            text,
            re.IGNORECASE,
        )
        if match:
            month = match.group("month").title()
            if source_year is None:
                return month
            return f"{month} {source_year}"
        return self._extract_period_text(text, source_year)

    @staticmethod
    def _scale_number(value: str, suffix: str | None) -> float:
        numeric = float(value.replace(",", ""))
        if suffix is None:
            return numeric
        if suffix.lower() == "k":
            return numeric * 1000
        if suffix.lower() == "m":
            return numeric * 1_000_000
        return numeric

    @staticmethod
    def _source_year(source_date: str | None) -> int | None:
        if not source_date:
            return None
        try:
            return date.fromisoformat(source_date).year
        except ValueError:
            return None

    def _find_schedule_release_date(
        self,
        text: str,
        index: int,
        source_year: int | None,
    ) -> str | None:
        if source_year is None:
            return None
        context = text[max(0, index - 2000):index]
        weekday_patterns = [
            r"(Monday|Tuesday|Wednesday|Thursday|Friday)\s+(?P<day>\d{1,2})\s+(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
            r"(Monday|Tuesday|Wednesday|Thursday|Friday)\s+(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(?P<day>\d{1,2})",
        ]
        last_match: re.Match[str] | None = None
        for pattern in weekday_patterns:
            for match in re.finditer(pattern, context, re.IGNORECASE):
                last_match = match
            if last_match is not None:
                break
        if last_match is None:
            return None
        day = last_match.group("day")
        month = last_match.group("month")
        month_number = self._MONTH_LOOKUP[month.lower()]
        return date(source_year, month_number, int(day)).isoformat()
