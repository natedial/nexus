"""Ops wiring tests — LIBRARY since-last-run, Grok Bot handoff, silent empty day."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from src.claim_notes.delivery import (
    FakeGrokBotChatPingSender,
    FakeRemarkableNotebookSender,
    HandoffGrokBotChatPingSender,
    HandoffRemarkableNotebookSender,
    morning_attention_chat_line,
    morning_attention_markdown,
)
from src.claim_notes.library import FakeLibraryDigestReader, LibraryResearchNote
from src.claim_notes.notion_library import FakeNotionTransport, NotionLibraryDigestReader
from src.claim_notes.ops import (
    MorningAttentionOps,
    intended_cron_expression,
    is_intended_weekday_slot,
)
from src.claim_notes.products.models import MorningAttentionDelivery
from src.claim_notes.project import project_argument_map_batch
from src.claim_notes.watermark import RunWatermarkStore

ET = ZoneInfo("America/New_York")
ARG_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "argument_map_documents.json"
)


def _notes():
    docs = json.loads(ARG_FIXTURE.read_text(encoding="utf-8"))["documents"]
    return project_argument_map_batch(docs)


class NotionLibraryTests(unittest.TestCase):
    def test_filter_is_research_note_and_since_last_run(self):
        transport = FakeNotionTransport(
            pages=[
                {
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "url": "https://notion.so/note",
                    "last_edited_time": "2026-10-04T12:00:00.000Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Weekend note"}],
                        },
                        "Summary": {
                            "type": "rich_text",
                            "rich_text": [{"plain_text": "Saved over the weekend"}],
                        },
                    },
                }
            ]
        )
        reader = NotionLibraryDigestReader(
            token="secret-test-token",
            transport=transport,
        )
        since = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
        notes = reader.list_research_notes(since=since)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "Weekend note")
        body = transport.calls[0]["body"]
        filt = body["filter"]
        self.assertEqual(filt["and"][0]["select"]["equals"], "Research Note")
        self.assertEqual(filt["and"][0]["property"], "Resource Type")
        self.assertIn("last_edited_time", filt["and"][1])
        self.assertTrue(
            transport.calls[0]["headers"]["Authorization"].startswith("Bearer ")
        )


class WatermarkAndOpsTests(unittest.TestCase):
    def test_fake_library_respects_since_last_run_not_last_night_only(self):
        reader = FakeLibraryDigestReader(
            [
                LibraryResearchNote(
                    title="Friday",
                    saved_at=datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc),
                ),
                LibraryResearchNote(
                    title="Saturday",
                    saved_at=datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc),
                ),
                LibraryResearchNote(
                    title="Sunday",
                    saved_at=datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        # Last run was Friday morning — weekend notes must appear (same as 6:10 example).
        since = datetime(2026, 10, 2, 10, 25, tzinfo=timezone.utc)
        got = reader.list_research_notes(since=since)
        titles = {n.title for n in got}
        self.assertEqual(titles, {"Friday", "Saturday", "Sunday"})

    def test_ops_run_delivers_own_surface_and_advances_watermark(self):
        with TemporaryDirectory() as tmp:
            watermark = RunWatermarkStore(Path(tmp) / "wm.json")
            remarkable = FakeRemarkableNotebookSender()
            chat = FakeGrokBotChatPingSender()
            reader = FakeLibraryDigestReader(
                [
                    LibraryResearchNote(
                        title="Lib A",
                        summary="Research note A",
                        saved_at=datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc),
                    )
                ]
            )
            ops = MorningAttentionOps(
                library_reader=reader,
                watermark=watermark,
                remarkable_sender=remarkable,
                chat_ping_sender=chat,
            )
            result = ops.run(
                notes=_notes(),
                calendar_events=[
                    {"event_date": "2026-10-06", "country": "US", "event_name": "Payrolls"}
                ],
                now=datetime(2026, 10, 5, 10, 25, tzinfo=timezone.utc),
            )
            self.assertFalse(result.silent)
            self.assertGreaterEqual(len(result.surface.points), 3)
            self.assertLessEqual(len(result.surface.points), 5)
            delivery = result.surface.delivery
            self.assertIsInstance(delivery, MorningAttentionDelivery)
            self.assertTrue(delivery.grok_bot_chat_ping)
            self.assertTrue(delivery.empty_day_silent)
            self.assertEqual(
                delivery.pattern, "own_remarkable_notebook_plus_grok_bot_ping"
            )
            self.assertFalse(delivery.fold_into_g10_calendar)
            self.assertFalse(delivery.fold_into_research_from)
            self.assertFalse(delivery.alter_tablet_555)
            self.assertFalse(delivery.alter_tablet_610)
            self.assertEqual(len(remarkable.pushes), 1)
            self.assertEqual(len(chat.messages), 1)
            self.assertEqual(chat.messages[0]["channel"], "grok_bot")
            self.assertIn("Morning attention ready", chat.messages[0]["body"])
            self.assertNotIn("subject", chat.messages[0])
            self.assertEqual(result.chat_ping["channel"], "grok_bot")
            self.assertIsNotNone(watermark.read())

    def test_handoff_writes_markdown_and_grok_ping_not_smtp(self):
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            watermark = RunWatermarkStore(Path(tmp) / "wm.json")
            ops = MorningAttentionOps(
                library_reader=FakeLibraryDigestReader([]),
                watermark=watermark,
                remarkable_sender=HandoffRemarkableNotebookSender(handoff),
                chat_ping_sender=HandoffGrokBotChatPingSender(handoff),
                handoff_dir=handoff,
            )
            result = ops.run(
                notes=_notes(),
                now=datetime(2026, 10, 5, 10, 25, tzinfo=timezone.utc),
            )
            self.assertFalse(result.silent)
            self.assertTrue((handoff / "morning-attention.md").is_file())
            self.assertTrue((handoff / "notebook-title.txt").is_file())
            ping = (handoff / "chat-ping.txt").read_text(encoding="utf-8").strip()
            self.assertEqual(ping.count("\n"), 0)
            self.assertIn("Morning attention ready", ping)
            manifest = json.loads((handoff / "handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["channel_chat"], "grok_bot")
            self.assertTrue(manifest["deliver_grok_bot_ping"])
            self.assertFalse(manifest["fold_into_g10_calendar"])
            self.assertFalse(manifest["alter_tablet_555"])
            self.assertFalse(manifest["alter_tablet_610"])

    def test_empty_day_is_silent_no_notebook_no_ping(self):
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            handoff.mkdir()
            # Stale artifacts from a prior non-silent day must be removed.
            (handoff / "morning-attention.md").write_text("# stale\n", encoding="utf-8")
            (handoff / "chat-ping.txt").write_text("stale ping\n", encoding="utf-8")
            (handoff / "notebook-title.txt").write_text("stale\n", encoding="utf-8")

            watermark = RunWatermarkStore(Path(tmp) / "wm.json")
            remarkable = FakeRemarkableNotebookSender()
            chat = FakeGrokBotChatPingSender()
            ops = MorningAttentionOps(
                library_reader=FakeLibraryDigestReader([]),
                watermark=watermark,
                remarkable_sender=remarkable,
                chat_ping_sender=chat,
                handoff_dir=handoff,
            )
            result = ops.run(
                notes=[],
                calendar_events=[],
                now=datetime(2026, 10, 5, 10, 25, tzinfo=timezone.utc),
            )
            self.assertTrue(result.silent)
            self.assertEqual(result.surface.points, [])
            self.assertIsNone(result.remarkable)
            self.assertIsNone(result.chat_ping)
            self.assertEqual(len(remarkable.pushes), 0)
            self.assertEqual(len(chat.messages), 0)
            self.assertFalse((handoff / "morning-attention.md").exists())
            self.assertFalse((handoff / "chat-ping.txt").exists())
            self.assertFalse((handoff / "notebook-title.txt").exists())
            manifest = json.loads((handoff / "handoff.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["silent"])
            self.assertEqual(manifest["reason"], "empty_day")
            self.assertFalse(manifest["deliver_remarkable"])
            self.assertFalse(manifest["deliver_grok_bot_ping"])
            self.assertIsNotNone(watermark.read())

    def test_file_remarkable_sender_writes_markdown(self):
        with TemporaryDirectory() as tmp:
            sender = HandoffRemarkableNotebookSender(tmp)
            from src.claim_notes.products.models import MorningAttentionSurface

            surface_md = morning_attention_markdown(
                MorningAttentionSurface(points=[]),
                title="Morning attention",
            )
            result = sender.push(
                title="Morning attention 2026-10-05", markdown=surface_md
            )
            self.assertTrue(Path(result.path).is_file())

    def test_chat_line_is_one_line(self):
        from src.claim_notes.products.models import (
            MorningAttentionPoint,
            MorningAttentionSurface,
        )

        surface = MorningAttentionSurface(
            points=[
                MorningAttentionPoint(rank=1, text="a", source="claim_note"),
                MorningAttentionPoint(rank=2, text="b", source="calendar"),
            ]
        )
        line = morning_attention_chat_line(surface, as_of="2026-10-05")
        self.assertEqual(line.count("\n"), 0)
        self.assertIn("2 points", line)

    def test_schedule_locks(self):
        self.assertEqual(intended_cron_expression(), "25 6 * * 1-5")
        monday = datetime(2026, 10, 5, 6, 25, tzinfo=ET)  # Monday
        saturday = datetime(2026, 10, 3, 6, 25, tzinfo=ET)
        self.assertTrue(is_intended_weekday_slot(monday))
        self.assertFalse(is_intended_weekday_slot(saturday))


if __name__ == "__main__":
    unittest.main()
