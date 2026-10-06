"""Tests for argument_map → ClaimNote projection + Gerhard validators."""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from src.claim_notes.project import (
    filter_argument_map_documents,
    load_argument_map_documents,
    project_argument_map_batch,
    project_argument_map_document,
    resolve_analyst_batch_path,
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

    def test_skips_library_desk_speaker(self):
        notes = project_argument_map_document(
            {
                "speaker": "LIBRARY desk",
                "publisher": "Notion LIBRARY",
                "argument_map": [{"claim": "services cool"}],
            }
        )
        self.assertEqual(notes, [])

    def test_skips_merged_desk_speaker(self):
        notes = project_argument_map_document(
            {
                "speaker": "JPM / Barclays",
                "publisher": "Street digest",
                "argument_map": [{"claim": "curve steepens"}],
            }
        )
        self.assertEqual(notes, [])

    def test_skips_multi_idea_claim_under_extract(self):
        notes = project_argument_map_document(
            {
                "speaker": "Jan Hatzius",
                "publisher": "Goldman Sachs",
                "argument_map": [
                    {
                        "claim": "the Fed is done hiking. Cuts come in Q2.",
                    },
                    {"claim": "one atomic claim only"},
                ],
            }
        )
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].claim, "one atomic claim only")

    def test_cause_edges_only_when_stated(self):
        notes = project_argument_map_document(
            {
                "speaker": "Ellen Zentner",
                "publisher": "Morgan Stanley",
                "argument_map": [
                    {"claim": "first cut in Q2"},
                    {
                        "claim": "labor softens",
                        "cause_edges": [
                            {
                                "cause": "weaker payrolls",
                                "effect": "earlier cut",
                                "polarity": "supports",
                            }
                        ],
                    },
                ],
            }
        )
        self.assertEqual(notes[0].cause_edges, [])
        self.assertEqual(len(notes[1].cause_edges), 1)

    def test_filter_since_until(self):
        kept = filter_argument_map_documents(
            self.docs, since=date(2026, 9, 14), until=date(2026, 9, 17)
        )
        keys = {d["document_key"] for d in kept}
        self.assertEqual(
            keys,
            {"citi-2026-09-14-inflation", "powell-2026-09-17-outlook"},
        )

    def test_load_and_resolve_batch_dir(self):
        docs = load_argument_map_documents(FIXTURE)
        self.assertEqual(len(docs), 5)
        with TemporaryDirectory() as tmp:
            batch = Path(tmp) / "dispatch-batch-x.json"
            batch.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            latest = Path(tmp) / "latest.json"
            latest.symlink_to(batch.name)
            resolved = resolve_analyst_batch_path(tmp)
            self.assertEqual(resolved.resolve(), batch.resolve())


if __name__ == "__main__":
    unittest.main()
