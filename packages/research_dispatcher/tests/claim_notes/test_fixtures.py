"""Fixture suite for claim-note-v1."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.claim_notes import CLAIM_NOTE_SCHEMA_VERSION, load_claim_notes
from src.claim_notes.validate import live_findings_allowed

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "claim_notes.jsonl"
)

ROLES = {"chair", "voter", "non-voter", "interview", "research_author"}


class FixtureTests(unittest.TestCase):
    def test_fixtures_load_and_validate(self):
        notes = load_claim_notes(FIXTURES)
        self.assertGreaterEqual(len(notes), 6)
        for note in notes:
            self.assertEqual(note.schema_version, CLAIM_NOTE_SCHEMA_VERSION)
            self.assertIn(note.thread_role, ("assert", "extend", "break"))
            self.assertIn(
                note.support_kind, ("ingested_document_text", "live_data")
            )
            self.assertIn(note.speaker_weight, ROLES)
            self.assertIsInstance(note.cause_edges, list)

    def test_fixtures_cover_thread_roles_and_cause_edges(self):
        notes = load_claim_notes(FIXTURES)
        roles = {n.thread_role for n in notes}
        self.assertEqual(roles, {"assert", "extend", "break"})
        with_edges = [n for n in notes if n.cause_edges]
        self.assertGreaterEqual(len(with_edges), 3)

    def test_fixtures_cover_awaiting_vs_completed_dexter(self):
        notes = {n.note_id: n for n in load_claim_notes(FIXTURES)}
        live = notes["cn-live-payrolls"]
        awaiting = notes["cn-live-awaiting-dexter"]
        self.assertTrue(live_findings_allowed(live))
        self.assertEqual(live.dexter_pass.status, "completed")
        self.assertFalse(live_findings_allowed(awaiting))
        self.assertEqual(awaiting.dexter_pass.status, "awaiting")
        self.assertEqual(awaiting.dexter_pass.findings, [])

    def test_speaker_publisher_distinct_on_powell(self):
        notes = {n.note_id: n for n in load_claim_notes(FIXTURES)}
        powell = notes["cn-powell-speech"]
        self.assertEqual(powell.speaker, "Jerome Powell")
        self.assertEqual(powell.publisher, "Federal Reserve Board")
        self.assertEqual(powell.speaker_weight, "chair")

    def test_extend_and_break_target_assert(self):
        notes = {n.note_id: n for n in load_claim_notes(FIXTURES)}
        self.assertEqual(
            notes["cn-extend-ms-q2-cut"].thread_target_note_id,
            "cn-assert-gs-fed-done",
        )
        self.assertEqual(
            notes["cn-break-citi-still-hiking"].thread_target_note_id,
            "cn-assert-gs-fed-done",
        )


if __name__ == "__main__":
    unittest.main()
