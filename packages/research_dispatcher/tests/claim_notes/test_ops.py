"""Ops wiring tests — Notion LIBRARY since-last-run, delivery, schedule locks."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from src.claim_notes.delivery import (
    FakeChatPingSender,
    FakeRemarkableNotebookSender,
    FileRemarkableNotebookSender,
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
        # Token used in Authorization — not asserted as plaintext beyond presence.
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
            chat = FakeChatPingSender()
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
            self.assertGreaterEqual(len(result.surface.points), 3)
            self.assertLessEqual(len(result.surface.points), 5)
            delivery = result.surface.delivery
            self.assertIsInstance(delivery, MorningAttentionDelivery)
            self.assertFalse(delivery.fold_into_g10_calendar)
            self.assertFalse(delivery.fold_into_research_from)
            self.assertFalse(delivery.alter_tablet_555)
            self.assertFalse(delivery.alter_tablet_610)
            self.assertEqual(len(remarkable.pushes), 1)
            self.assertEqual(len(chat.messages), 1)
            self.assertIn("Morning attention ready", chat.messages[0]["body"])
            self.assertIsNotNone(watermark.read())

    def test_file_remarkable_sender_writes_markdown(self):
        with TemporaryDirectory() as tmp:
            sender = FileRemarkableNotebookSender(tmp)
            surface_md = morning_attention_markdown(
                __import__(
                    "src.claim_notes.products.models", fromlist=["MorningAttentionSurface"]
                ).MorningAttentionSurface(
                    points=[],
                ),
                title="Morning attention",
            )
            result = sender.push(title="Morning attention 2026-10-05", markdown=surface_md)
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
