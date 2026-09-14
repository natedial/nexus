from __future__ import annotations

import unittest

from research_analysis_layer.models import ParsedDocument
from research_analysis_layer.services.raw_forecast_extractor import RawForecastExtractor


class RawForecastExtractorTest(unittest.TestCase):
    def test_extracts_calendar_style_forecast_block_from_full_text(self) -> None:
        full_text = """
Employment (Friday Apr 4 release):

Headline NFP: +60k; Private payrolls: +70k
Unemployment rate: 4.4% (unchanged); Average hourly earnings: +0.3% m/m; Labor force participation: 62.0%; Avg weekly hours: 34.3

ADP (Wednesday Apr 2):

MS forecast: +40k (vs. prior +63k)

Retail Sales (Wednesday Apr 2 — February data):

Headline: +0.6% m/m; Ex-auto: +0.3% m/m; Control group: +0.2% m/m.

ISM Manufacturing (Wednesday Apr 2 — March):

MS tracking: 53.0, up from 52.4 in February.
"""
        document = ParsedDocument(
            id=5194,
            document_name="ms_oil_prices.pdf",
            source="Morgan Stanley",
            source_date="2026-03-29",
            parsed_data={"full_text": full_text},
            document_link="https://example.com/doc.pdf",
            document_hash="hash-5194",
        )

        candidates = RawForecastExtractor().extract(
            document=document,
            file_id="file-5194",
            created_run_id=42,
        )

        candidate_map = {candidate.indicator_key: candidate for candidate in candidates}
        self.assertEqual(candidate_map["us_nfp"].forecast_value_numeric, 60000.0)
        self.assertEqual(candidate_map["us_private_payrolls"].forecast_value_numeric, 70000.0)
        self.assertEqual(candidate_map["us_unemployment_rate"].forecast_value_numeric, 4.4)
        self.assertEqual(candidate_map["us_average_hourly_earnings_mom"].forecast_value_numeric, 0.3)
        self.assertEqual(candidate_map["us_labor_force_participation_rate"].forecast_value_numeric, 62.0)
        self.assertEqual(candidate_map["us_average_weekly_hours"].forecast_value_numeric, 34.3)
        self.assertEqual(candidate_map["us_adp_employment_change"].forecast_value_numeric, 40000.0)
        self.assertEqual(candidate_map["us_retail_sales_headline_mom"].forecast_value_numeric, 0.6)
        self.assertEqual(candidate_map["us_retail_sales_ex_auto_mom"].forecast_value_numeric, 0.3)
        self.assertEqual(candidate_map["us_retail_sales_control_group_mom"].forecast_value_numeric, 0.2)
        self.assertEqual(candidate_map["us_ism_manufacturing"].forecast_value_numeric, 53.0)
        self.assertEqual(candidate_map["us_nfp"].release_date, "2026-04-04")
        self.assertEqual(candidate_map["us_adp_employment_change"].release_date, "2026-04-02")

    def test_extracts_table_row_aliases_and_weekday_header_dates(self) -> None:
        full_text = """
Wednesday Apr 2

8:15 AM  ADP Employment Change  Mar  40  63
8:30 AM  Retail Sales Advance m/m  Feb  0.6  0.4  -0.2
8:30 AM  Retail Sales Ex Auto m/m  Feb  0.3  0.3  0.0
8:30 AM  Retail Sales Control Group  Feb  0.2  0.3
10:00 AM  ISM Manufacturing  Mar  53.0  52.1  52.4
"""
        document = ParsedDocument(
            id=6001,
            document_name="calendar_table.pdf",
            source="Morgan Stanley",
            source_date="2026-03-29",
            parsed_data={"full_text": full_text},
            document_link="https://example.com/calendar.pdf",
            document_hash="hash-6001",
        )

        candidates = RawForecastExtractor().extract(
            document=document,
            file_id="file-6001",
            created_run_id=42,
        )

        candidate_map = {candidate.indicator_key: candidate for candidate in candidates}
        self.assertEqual(candidate_map["us_adp_employment_change"].forecast_value_numeric, 40000.0)
        self.assertEqual(candidate_map["us_adp_employment_change"].release_date, "2026-04-02")
        self.assertEqual(candidate_map["us_retail_sales_headline_mom"].forecast_value_numeric, 0.6)
        self.assertEqual(candidate_map["us_retail_sales_headline_mom"].release_date, "2026-04-02")
        self.assertEqual(candidate_map["us_retail_sales_ex_auto_mom"].forecast_value_numeric, 0.3)
        self.assertEqual(candidate_map["us_retail_sales_control_group_mom"].forecast_value_numeric, 0.2)
        self.assertEqual(candidate_map["us_ism_manufacturing"].forecast_value_numeric, 53.0)

    def test_merges_employment_prose_with_table_metadata(self) -> None:
        full_text = """
Employment:

For March employment, we expect headline and private payrolls to rise by 60k and 70k, respectively,
and for the unemployment rate to hold steady at 4.4%.
Job openings data for February will also be reported in the coming week.

Friday Apr 3

8:30 AM  Change in Nonfarm Payrolls  Mar  60  50  -92
8:30 AM  Change in Private Payrolls  Mar  70  49  -86
8:30 AM  Unemployment Rate  Mar  4.4  4.4  4.4
"""
        document = ParsedDocument(
            id=6002,
            document_name="employment_period.pdf",
            source="Morgan Stanley",
            source_date="2026-03-29",
            parsed_data={"full_text": full_text},
            document_link="https://example.com/employment.pdf",
            document_hash="hash-6002",
        )

        candidates = RawForecastExtractor().extract(
            document=document,
            file_id="file-6002",
            created_run_id=42,
        )

        candidate_map = {candidate.indicator_key: candidate for candidate in candidates}
        self.assertEqual(candidate_map["us_nfp"].period_text, "March 2026")
        self.assertEqual(candidate_map["us_private_payrolls"].period_text, "March 2026")
        self.assertEqual(candidate_map["us_unemployment_rate"].period_text, "March 2026")
        self.assertEqual(candidate_map["us_nfp"].release_date, "2026-04-03")
        self.assertEqual(candidate_map["us_private_payrolls"].release_date, "2026-04-03")
        self.assertEqual(candidate_map["us_unemployment_rate"].release_date, "2026-04-03")


if __name__ == "__main__":
    unittest.main()
