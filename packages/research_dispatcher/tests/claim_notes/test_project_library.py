"""LIBRARY Research Note projection — demoted; not the live 6:25 claim feed."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.claim_notes.library import LibraryResearchNote, PrefilteredLibraryDigestReader
from src.claim_notes.ops import MorningAttentionOps
from src.claim_notes.project_library import (
    LIBRARY_PUBLISHER,
    LIBRARY_SPEAKER,
    project_library_research_note,
    project_library_research_notes,
)
from src.claim_notes.delivery import (
    FakeGrokBotChatPingSender,
    FakeRemarkableNotebookSender,
    HandoffGrokBotChatPingSender,
    HandoffRemarkableNotebookSender,
)
from src.claim_notes.watermark import RunWatermarkStore
from src.claim_notes.run_morning_attention import main as run_main


class ProjectLibraryTests(unittest.TestCase):
    def test_projects_summary_as_stated_no_dexter_no_invented_numbers(self):
        note = LibraryResearchNote(
            title="Services cool",
            note_id="lib-1",
            summary="services disinflation continues",
            source_date=__import__("datetime").date(2026, 10, 5),
            saved_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
            url="https://notion.so/lib-1",
        )
        claim = project_library_research_note(note)
        assert claim is not None
        self.assertEqual(claim.note_id, "lib-1")
        self.assertEqual(claim.claim, "services disinflation continues")
        self.assertEqual(claim.speaker, LIBRARY_SPEAKER)
        self.assertEqual(claim.publisher, LIBRARY_PUBLISHER)
        self.assertNotEqual(claim.speaker, claim.publisher)
        self.assertEqual(claim.support_kind, "ingested_document_text")
        self.assertIsNone(claim.dexter_pass)
        self.assertEqual(claim.cause_edges, [])
        self.assertEqual(claim.speaker_weight, "research_author")
        self.assertEqual(claim.thread_role, "assert")

    def test_skips_blank_rows(self):
        notes = project_library_research_notes(
            [LibraryResearchNote(title="", summary="")]
        )
        self.assertEqual(notes, [])


class LibraryDemotedOpsTests(unittest.TestCase):
    def test_library_alone_does_not_project_claims_silent(self):
        """Live ops must not use project_library when claim notes are empty."""
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            watermark = RunWatermarkStore(Path(tmp) / "wm.json")
            watermark.write(datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc))
            reader = PrefilteredLibraryDigestReader(
                [
                    LibraryResearchNote(
                        title="Note A",
                        note_id="a",
                        summary="first library claim as stated",
                        saved_at=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc),
                    ),
                    LibraryResearchNote(
                        title="Note B",
                        note_id="b",
                        summary="second library claim as stated",
                        saved_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
                    ),
                    LibraryResearchNote(
                        title="Note C",
                        note_id="c",
                        summary="third library claim as stated",
                        saved_at=datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc),
                    ),
                ]
            )
            ops = MorningAttentionOps(
                library_reader=reader,
                watermark=watermark,
                remarkable_sender=HandoffRemarkableNotebookSender(handoff),
                chat_ping_sender=HandoffGrokBotChatPingSender(handoff),
                handoff_dir=handoff,
            )
            result = ops.run(
                notes=[],
                calendar_events=[],
                now=datetime(2026, 10, 6, 10, 25, tzinfo=timezone.utc),
            )
            self.assertTrue(result.silent)
            self.assertEqual(len(result.library_notes), 3)
            self.assertEqual(result.surface.points, [])
            self.assertFalse((handoff / "morning-attention.md").exists())

    def test_empty_library_is_silent_no_fixture_needed(self):
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            handoff.mkdir()
            (handoff / "morning-attention.md").write_text("stale\n", encoding="utf-8")
            (handoff / "chat-ping.txt").write_text("stale\n", encoding="utf-8")
            ops = MorningAttentionOps(
                library_reader=PrefilteredLibraryDigestReader([]),
                watermark=RunWatermarkStore(Path(tmp) / "wm.json"),
                remarkable_sender=FakeRemarkableNotebookSender(),
                chat_ping_sender=FakeGrokBotChatPingSender(),
                handoff_dir=handoff,
            )
            result = ops.run(
                notes=[],
                calendar_events=[],
                now=datetime(2026, 10, 6, 10, 25, tzinfo=timezone.utc),
            )
            self.assertTrue(result.silent)
            self.assertEqual(result.surface.points, [])
            self.assertFalse((handoff / "morning-attention.md").exists())
            self.assertFalse((handoff / "chat-ping.txt").exists())
            manifest = json.loads((handoff / "handoff.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["silent"])
            self.assertEqual(manifest["reason"], "empty_day")

    def test_cli_library_json_alone_silent_no_claim_projection(self):
        with TemporaryDirectory() as tmp:
            lib_path = Path(tmp) / "library.json"
            handoff = Path(tmp) / "handoff"
            watermark = Path(tmp) / "wm.json"
            lib_path.write_text(
                json.dumps(
                    [
                        {
                            "title": "Payrolls note",
                            "note_id": "p1",
                            "summary": "payrolls undershot as stated in library",
                            "saved_at": "2026-10-05T12:00:00+00:00",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            from io import StringIO
            from contextlib import redirect_stdout

            buf = StringIO()
            with redirect_stdout(buf):
                code = run_main(
                    [
                        "--library-json",
                        str(lib_path),
                        "--handoff-dir",
                        str(handoff),
                        "--watermark",
                        str(watermark),
                    ]
                )
            self.assertEqual(code, 0)
            manifest = json.loads((handoff / "handoff.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["silent"])
            self.assertFalse((handoff / "morning-attention.md").exists())


if __name__ == "__main__":
    unittest.main()
