"""Fixture-driven tests for the five claim-note product surfaces."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from src.claim_notes.library import (
    LIBRARY_NOTION_URL,
    LIBRARY_RESOURCE_TYPE_FILTER,
    FakeLibraryDigestReader,
    LibraryResearchNote,
)
from src.claim_notes.load import load_claim_notes
from src.claim_notes.products import (
    author_evolution,
    build_morning_attention,
    impromptu_study,
    recent_ingest,
    thematic_digest,
)
from src.claim_notes.project import project_argument_map_batch

ARG_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "argument_map_documents.json"
)
NOTES_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "claim_notes.jsonl"
)


class ProductTests(unittest.TestCase):
    def setUp(self) -> None:
        docs = json.loads(ARG_FIXTURE.read_text(encoding="utf-8"))["documents"]
        self.notes = project_argument_map_batch(docs)
        self.fixture_notes = load_claim_notes(NOTES_FIXTURE)

    def test_recent_ingest_since_watermark(self):
        result = recent_ingest(self.notes, since=date(2026, 9, 13))
        self.assertEqual(result.since, date(2026, 9, 13))
        dates = [n.source_date for n in result.notes]
        self.assertTrue(dates)
        self.assertTrue(all(d and d > date(2026, 9, 13) for d in dates))

    def test_thematic_digest_sides_are_thread_stances(self):
        result = thematic_digest(self.notes)
        thread = next(
            t for t in result.threads if t.thread_key == "claim:fed:hiking_done"
        )
        stances = {side.stance for side in thread.sides}
        # Thread-local stances from the maps — not global hawk/dove.
        self.assertIn("done_hiking", stances)
        self.assertIn("more_hikes_possible", stances)
        self.assertNotIn("hawk", stances)
        self.assertNotIn("dove", stances)

    def test_morning_attention_own_surface_and_delivery(self):
        library = FakeLibraryDigestReader(
            [
                LibraryResearchNote(
                    title="LIBRARY note A",
                    summary="Research note summary A",
                    source_date=date(2026, 10, 1),
                )
            ]
        )
        surface = build_morning_attention(
            self.notes,
            calendar_events=[
                {
                    "event_date": "2026-10-06",
                    "country": "US",
                    "event_name": "Payrolls",
                }
            ],
            library=library,
            max_points=5,
        )
        self.assertGreaterEqual(len(surface.points), 3)
        self.assertLessEqual(len(surface.points), 5)
        self.assertTrue(surface.delivery.remarkable_notebook)
        self.assertTrue(surface.delivery.chat_ping)
        self.assertFalse(surface.delivery.fold_into_g10_calendar)
        self.assertFalse(surface.delivery.fold_into_research_from)
        self.assertFalse(surface.delivery.alter_tablet_555)
        self.assertFalse(surface.delivery.alter_tablet_610)
        self.assertEqual(LIBRARY_RESOURCE_TYPE_FILTER, "Research Note")
        self.assertIn("notion.com", LIBRARY_NOTION_URL)

    def test_author_evolution_keeps_publisher_distinct(self):
        result = author_evolution(self.notes, speaker="Jerome Powell")
        self.assertEqual(result.speaker, "Jerome Powell")
        self.assertGreaterEqual(len(result.events), 2)
        self.assertTrue(all(e.publisher == "Federal Reserve Board" for e in result.events))
        self.assertGreaterEqual(result.extend_or_break_count, 1)
        dates = [e.source_date for e in result.events]
        self.assertEqual(dates, sorted(dates, key=lambda d: d or date.min))

    def test_impromptu_study_marks_dexter_pointer_without_inventing(self):
        result = impromptu_study(
            self.notes, query="hiking", need_live_numbers=True
        )
        self.assertGreaterEqual(len(result.hits), 1)
        self.assertEqual(len(result.dexter_pointers), 1)
        self.assertEqual(result.dexter_pointers[0].status, "awaiting")
        self.assertEqual(result.dexter_pointers[0].findings, [])
        self.assertFalse(result.live_numbers_invented)

    def test_fixture_notes_feed_recent_ingest(self):
        result = recent_ingest(self.fixture_notes, since=date(2026, 9, 12))
        self.assertTrue(result.note_ids)


if __name__ == "__main__":
    unittest.main()
