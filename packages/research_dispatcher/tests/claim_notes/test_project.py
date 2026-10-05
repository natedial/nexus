"""Tests for argument_map → ClaimNote projection."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.claim_notes.project import (
    project_argument_map_batch,
    project_argument_map_document,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "argument_map_documents.json"
)


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = json.loads(FIXTURE.read_text(encoding="utf-8"))["documents"]

    def test_projects_claims_with_distinct_speaker_publisher(self):
        notes = project_argument_map_document(self.docs[0])
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note.speaker, "Jan Hatzius")
        self.assertEqual(note.publisher, "Goldman Sachs")
        self.assertEqual(note.speaker_weight, "research_author")
        self.assertEqual(note.support_kind, "ingested_document_text")
        self.assertEqual(note.thread_role, "assert")
        self.assertEqual(len(note.cause_edges), 1)
        self.assertEqual(note.stance, "done_hiking")

    def test_preserves_extend_and_break(self):
        notes = project_argument_map_batch(self.docs)
        by_speaker = {n.speaker: n for n in notes if n.thread_role != "assert"}
        self.assertEqual(by_speaker["Ellen Zentner"].thread_role, "extend")
        self.assertEqual(by_speaker["Andrew Hollenhorst"].thread_role, "break")

    def test_does_not_invent_live_data(self):
        for note in project_argument_map_batch(self.docs):
            self.assertEqual(note.support_kind, "ingested_document_text")
            self.assertIsNone(note.dexter_pass)

    def test_chair_weight_on_powell(self):
        notes = project_argument_map_document(self.docs[3])
        self.assertEqual(notes[0].speaker_weight, "chair")
        self.assertEqual(notes[0].speaker, "Jerome Powell")
        self.assertEqual(notes[0].publisher, "Federal Reserve Board")

    def test_requires_identity(self):
        with self.assertRaises(ValueError):
            project_argument_map_document({"argument_map": [{"claim": "x"}]})


if __name__ == "__main__":
    unittest.main()
