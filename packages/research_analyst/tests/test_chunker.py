from __future__ import annotations

import unittest

from research_analysis_layer.models import HydratedParsedDocument, HydratedTheme, ParsedDocument, ParsedTheme
from research_analysis_layer.services.chunker import Chunker


class ChunkerTest(unittest.TestCase):
    def test_creates_forecast_chunk_from_theme(self) -> None:
        document = ParsedDocument(
            id=1,
            document_name="doc.pdf",
            source="Test",
            source_date="2026-03-29",
            parsed_data={},
            theme_count=1,
            document_hash="hash",
        )
        theme = ParsedTheme(
            id=5,
            research_id=1,
            theme_order=1,
            label="Cuts are delayed",
            scope=None,
            primary_category="Macro",
            relevance=["Macro", "Rates"],
            classification="Forecast",
            strength="Primary",
            confidence="High",
            evidence_count=0,
            mention_count=0,
            context="Cuts are less likely in June.",
            directionality=None,
            argument_structure=None,
        )
        hydrated = HydratedParsedDocument(
            document=document,
            themes=[HydratedTheme(theme=theme)],
            file_id="file-1",
        )
        chunks = Chunker().chunk_document(hydrated)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_type, "forecast_block")
        self.assertEqual(chunks[0].title, "Cuts are delayed")


if __name__ == "__main__":
    unittest.main()
