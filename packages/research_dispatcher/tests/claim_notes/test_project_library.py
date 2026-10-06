"""Gerhard LIBRARY body extraction — multi-claim, real speakers, no scaffolding."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.claim_notes.delivery import (
    FakeGrokBotChatPingSender,
    FakeRemarkableNotebookSender,
    HandoffGrokBotChatPingSender,
    HandoffRemarkableNotebookSender,
)
from src.claim_notes.library import LibraryResearchNote, PrefilteredLibraryDigestReader
from src.claim_notes.ops import MorningAttentionOps
from src.claim_notes.project_library import (
    LIBRARY_PUBLISHER,
    extract_claims_from_library_note,
    project_library_research_note,
    project_library_research_notes,
)
from src.claim_notes.run_morning_attention import main as run_main
from src.claim_notes.watermark import RunWatermarkStore

MULTI_CLAIM_BODY = """\
Speaker: JPM Rates
Publisher: JPMorgan

Claim: the Fed is done hiking this cycle
Thread: assert

Claim: first cut comes in Q2
Thread: extend
Thread_target: cn-assert-gs-fed-done
Stance: earlier_cuts
Cause: cooling services -> earlier cut (supports)

Claim: payrolls undershot as stated in the desk note
Thread: assert
"""


class GerhardBodyExtractionTests(unittest.TestCase):
    def test_multi_claim_from_one_body(self):
        note = LibraryResearchNote(
            title="JPM rates morning",
            note_id="jpm-1",
            body=MULTI_CLAIM_BODY,
            source_date=date(2026, 10, 5),
        )
        claims = extract_claims_from_library_note(note)
        self.assertEqual(len(claims), 3)
        self.assertEqual(claims[0].claim, "the Fed is done hiking this cycle")
        self.assertEqual(claims[1].claim, "first cut comes in Q2")
        self.assertEqual(claims[2].claim, "payrolls undershot as stated in the desk note")

    def test_speaker_is_attributed_desk_never_library_desk(self):
        note = LibraryResearchNote(
            title="Barclays note",
            note_id="barc-1",
            speaker="Barclays Economics",
            body=(
                "Claim: core services disinflation continues as stated\n"
                "Thread: assert\n"
            ),
        )
        claims = project_library_research_note(note)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].speaker, "Barclays Economics")
        self.assertNotEqual(claims[0].speaker.lower(), "library desk")
        self.assertNotIn("library desk", claims[0].speaker.lower())

    def test_publisher_defaults_to_notion_library_when_unstated(self):
        note = LibraryResearchNote(
            title="Desk note",
            note_id="d1",
            speaker="Citi Rates",
            body="Claim: shelter stays sticky into H1\nThread: assert\n",
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].publisher, LIBRARY_PUBLISHER)

    def test_publisher_uses_note_source_when_present(self):
        note = LibraryResearchNote(
            title="GS note",
            note_id="gs-1",
            speaker="Jan Hatzius",
            publisher="Goldman Sachs",
            body="Claim: the Fed is done hiking\nThread: assert\n",
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].speaker, "Jan Hatzius")
        self.assertEqual(claims[0].publisher, "Goldman Sachs")
        self.assertNotEqual(claims[0].speaker, claims[0].publisher)

    def test_side_null_when_unstated_no_invented_hawk_dove(self):
        note = LibraryResearchNote(
            title="MS note",
            note_id="ms-1",
            speaker="Ellen Zentner",
            body="Claim: first cut comes in Q2\nThread: assert\n",
        )
        claims = project_library_research_note(note)
        self.assertIsNone(claims[0].stance)
        self.assertNotEqual(claims[0].stance, "hawk")
        self.assertNotEqual(claims[0].stance, "dove")

    def test_side_as_stated_when_present(self):
        note = LibraryResearchNote(
            title="MS note",
            note_id="ms-2",
            speaker="Ellen Zentner",
            body=(
                "Claim: first cut comes in Q2\n"
                "Thread: assert\n"
                "Stance: earlier_cuts\n"
            ),
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].stance, "earlier_cuts")

    def test_empty_cause_edges_and_null_dexter_when_not_asserted(self):
        note = LibraryResearchNote(
            title="Plain note",
            note_id="p1",
            speaker="JPM",
            body="Claim: growth slows into year-end as stated\nThread: assert\n",
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].cause_edges, [])
        self.assertEqual(claims[0].support_kind, "ingested_document_text")
        self.assertIsNone(claims[0].dexter_pass)

    def test_explicit_cause_edge_only_when_stated(self):
        note = LibraryResearchNote(
            title="Causal note",
            note_id="c1",
            speaker="JPM",
            body=(
                "Claim: no further hikes this cycle\n"
                "Thread: assert\n"
                "Cause: services disinflation -> no further hikes (supports)\n"
            ),
        )
        claims = project_library_research_note(note)
        self.assertEqual(len(claims[0].cause_edges), 1)
        edge = claims[0].cause_edges[0]
        self.assertEqual(edge.cause, "services disinflation")
        self.assertEqual(edge.effect, "no further hikes")
        self.assertEqual(edge.polarity, "supports")

    def test_default_assert_when_no_prior_thread(self):
        note = LibraryResearchNote(
            title="No target",
            note_id="t1",
            speaker="Citi",
            body=(
                "Claim: one more hike remains possible\n"
                "Thread: break\n"
            ),
        )
        claims = project_library_research_note(note)
        # No thread_target → default assert (cannot invent prior thread).
        self.assertEqual(claims[0].thread_role, "assert")
        self.assertIsNone(claims[0].thread_target_note_id)

    def test_extend_when_prior_thread_stated(self):
        note = LibraryResearchNote(
            title="Extend",
            note_id="t2",
            speaker="MS",
            body=(
                "Claim: first cut comes in Q2\n"
                "Thread: extend\n"
                "Thread_target: cn-assert-gs-fed-done\n"
            ),
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].thread_role, "extend")
        self.assertEqual(claims[0].thread_target_note_id, "cn-assert-gs-fed-done")

    def test_title_summary_alone_is_not_enough(self):
        note = LibraryResearchNote(
            title="Services cool",
            summary="services disinflation continues",
            speaker="JPM",
            body="",
        )
        self.assertEqual(project_library_research_note(note), [])

    def test_rejects_library_desk_speaker(self):
        note = LibraryResearchNote(
            title="Bad",
            note_id="bad",
            speaker="LIBRARY desk",
            body="Claim: something as stated\nThread: assert\n",
        )
        self.assertEqual(project_library_research_note(note), [])

    def test_no_invented_numbers_copies_claim_as_stated(self):
        note = LibraryResearchNote(
            title="Prints",
            note_id="n1",
            speaker="BLS desk",
            body="Claim: payrolls undershot consensus last print\nThread: assert\n",
        )
        claims = project_library_research_note(note)
        self.assertEqual(claims[0].claim, "payrolls undershot consensus last print")
        # No fabricated figures attached.
        self.assertIsNone(claims[0].dexter_pass)

    def test_batch_skips_blank_rows(self):
        notes = project_library_research_notes(
            [LibraryResearchNote(title="", summary="", body="")]
        )
        self.assertEqual(notes, [])


class LibraryOnlyOpsTests(unittest.TestCase):
    def _body(self, claim: str) -> str:
        return f"Speaker: JPM Rates\n\nClaim: {claim}\nThread: assert\n"

    def test_library_json_body_extraction_drives_morning_attention(self):
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            watermark = RunWatermarkStore(Path(tmp) / "wm.json")
            reader = PrefilteredLibraryDigestReader(
                [
                    LibraryResearchNote(
                        title="Note A",
                        note_id="a",
                        body=self._body("first library claim as stated"),
                        saved_at=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc),
                    ),
                    LibraryResearchNote(
                        title="Note B",
                        note_id="b",
                        body=self._body("second library claim as stated"),
                        saved_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
                    ),
                    LibraryResearchNote(
                        title="Note C",
                        note_id="c",
                        body=self._body("third library claim as stated"),
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
            self.assertFalse(result.silent)
            self.assertGreaterEqual(len(result.surface.points), 3)
            self.assertTrue(all(p.source == "claim_note" for p in result.surface.points))
            for point in result.surface.points:
                self.assertIn("JPM Rates:", point.text)
                self.assertNotIn("LIBRARY desk", point.text)
            title = (handoff / "notebook-title.txt").read_text(encoding="utf-8").strip()
            self.assertEqual(title, "Morning Attention 2026-10-06")

    def test_empty_library_is_silent(self):
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
            self.assertFalse((handoff / "morning-attention.md").exists())
            self.assertFalse((handoff / "chat-ping.txt").exists())

    def test_cli_library_json_with_body(self):
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
                            "speaker": "JPM Rates",
                            "body": (
                                "Claim: payrolls undershot as stated in library\n"
                                "Thread: assert\n\n"
                                "Claim: ISM manufacturing below 50 as stated\n"
                                "Thread: assert\n\n"
                                "Claim: core CPI cooled as stated\n"
                                "Thread: assert\n"
                            ),
                            "saved_at": "2026-10-05T12:00:00+00:00",
                        }
                    ]
                ),
                encoding="utf-8",
            )
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
            self.assertFalse(manifest["silent"])
            self.assertGreaterEqual(manifest["point_count"], 3)


if __name__ == "__main__":
    unittest.main()
