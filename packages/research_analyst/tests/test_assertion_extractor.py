from __future__ import annotations

import unittest

from research_analysis_layer.models import AnalysisChunkDraft, EvidenceUnitDraft
from research_analysis_layer.services.assertion_extractor import AssertionExtractor


class AssertionExtractorTest(unittest.TestCase):
    def test_extracts_forecast_assertion(self) -> None:
        chunk = AnalysisChunkDraft(
            chunk_order=1,
            chunk_type="forecast_block",
            title="Delayed cuts",
            text="Cuts are less likely in June.",
        )
        evidence = [
            EvidenceUnitDraft(
                chunk_order=1,
                evidence_order=1,
                evidence_type="theme_context",
                text="Cuts are less likely in June.",
            )
        ]
        assertions = AssertionExtractor().extract(chunk, evidence)
        self.assertEqual(len(assertions), 1)
        self.assertEqual(assertions[0].assertion_type, "forecast")
        self.assertIn("Delayed cuts", assertions[0].text)
        self.assertEqual(assertions[0].subject_text, "Delayed cuts")

    def test_extracts_causal_and_risk_metadata(self) -> None:
        chunk = AnalysisChunkDraft(
            chunk_order=2,
            chunk_type="market_view",
            title="Dollar pressure",
            text="Higher tariff risk drives a stronger dollar. If inflation re-accelerates, yields could move higher.",
        )
        evidence = [
            EvidenceUnitDraft(
                chunk_order=2,
                evidence_order=1,
                evidence_type="theme_context",
                text=chunk.text,
            )
        ]

        assertions = AssertionExtractor().extract(chunk, evidence)

        self.assertEqual(len(assertions), 2)
        self.assertEqual(assertions[0].assertion_type, "market_impact")
        self.assertEqual(assertions[0].subject_text, "Higher tariff risk")
        self.assertEqual(assertions[0].object_text, "a stronger dollar")
        self.assertEqual(assertions[1].assertion_type, "risk_condition")
        self.assertIn("if inflation re-accelerates", (assertions[1].condition_text or "").lower())


if __name__ == "__main__":
    unittest.main()
