from __future__ import annotations

from datetime import datetime
import unittest

from research_analysis_layer.models import (
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedTheme,
    ParserStateRecord,
)
from research_analysis_layer.services.selector import Selector


class FakeStore:
    def __init__(self, already_processed: bool = False, previous_hash: str | None = None):
        self.already_processed = already_processed
        self.previous_hash = previous_hash

    def get_document_version_status(self, research_id: int, document_hash: str, analysis_version: str):
        del research_id
        del document_hash
        del analysis_version
        return self.already_processed, self.previous_hash


def make_state_record() -> ParserStateRecord:
    now = datetime.fromisoformat("2026-03-29T00:00:00+00:00")
    return ParserStateRecord(
        file_id="file-1",
        file_name="doc.pdf",
        status="completed",
        created_at=now,
        updated_at=now,
        storage_ok=True,
    )


def make_document(document_hash: str = "abc123", theme_count: int = 1, actual_themes: int = 1):
    document = ParsedDocument(
        id=1,
        document_name="doc.pdf",
        source="Test Bank",
        source_date="2026-03-29",
        parsed_data={},
        theme_count=theme_count,
        document_hash=document_hash,
    )
    theme = ParsedTheme(
        id=10,
        research_id=1,
        theme_order=1,
        label="Higher term premium",
        scope=None,
        primary_category="Rates",
        relevance=["Rates"],
        classification="Forecast",
        strength="Primary",
        confidence="High",
        evidence_count=1,
        mention_count=1,
        context="Term premium should remain elevated.",
        directionality=None,
        argument_structure=None,
    )
    return HydratedParsedDocument(
        document=document,
        themes=[HydratedTheme(theme=theme)] * actual_themes,
        file_id="file-1",
    )


class SelectorTest(unittest.TestCase):
    def test_selects_new_document(self) -> None:
        selector = Selector()
        decision = selector.decide(make_state_record(), make_document(), FakeStore(), "v1")
        self.assertTrue(decision.selected)
        self.assertEqual(decision.reason, "new_document")

    def test_skips_unready_document(self) -> None:
        selector = Selector()
        decision = selector.decide(
            make_state_record(),
            make_document(theme_count=2, actual_themes=1),
            FakeStore(),
            "v1",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "skipped_not_ready")

    def test_skips_duplicate_hash_and_version(self) -> None:
        selector = Selector()
        decision = selector.decide(
            make_state_record(),
            make_document(),
            FakeStore(already_processed=True, previous_hash="abc123"),
            "v1",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "skipped_duplicate")


if __name__ == "__main__":
    unittest.main()
