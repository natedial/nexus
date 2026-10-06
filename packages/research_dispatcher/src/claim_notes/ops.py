"""Orchestrate morning-attention ops for Proey's 6:25 ET routine.

Canonical path (Proey-owned weekday ~06:25 America/New_York, after 06:10):
  1) Run morning attention → markdown + one-line Grok Bot ping (local handoff)
  2) Proey pushes notebook titled "Morning Attention YYYY-MM-DD" via the same
     reMarkable connector as 5:55/6:10, placed next to G10 Calendar / Research From
  3) Proey sends the one-line Grok Bot ping to Nate's 1:1 chat with Proey
     (same destination as 5:55/6:10)

Empty day = silent: no notebook, no chat ping (same as the 6:40 handwritten pass).
Does not change 5:55 / 6:10 tablet pushes. Does not fold into G10 / Research From.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.claim_notes.delivery import (
    FakeGrokBotChatPingSender,
    FakeRemarkableNotebookSender,
    morning_attention_chat_line,
    morning_attention_markdown,
)
from src.claim_notes.library import (
    LIBRARY_RESOURCE_TYPE_FILTER,
    LibraryDigestInput,
    LibraryDigestReader,
    LibraryResearchNote,
)
from src.claim_notes.models import ClaimNote
from src.claim_notes.products.morning_attention import build_morning_attention
from src.claim_notes.products.models import MorningAttentionSurface
from src.claim_notes.watermark import RunWatermarkStore

ET = ZoneInfo("America/New_York")
MORNING_ATTENTION_HOUR_ET = 6
MORNING_ATTENTION_MINUTE_ET = 25
MORNING_ATTENTION_WEEKDAYS = (0, 1, 2, 3, 4)  # Mon–Fri


@dataclass
class MorningAttentionRunResult:
    surface: MorningAttentionSurface
    since: datetime | None
    library_notes: list[LibraryResearchNote]
    silent: bool = False
    remarkable: dict[str, Any] | None = None
    chat_ping: dict[str, Any] | None = None
    handoff_manifest: dict[str, Any] | None = None
    watermark_written: datetime | None = None
    dry_run: bool = False


@dataclass
class MorningAttentionOps:
    """Injectable ops runner — Proey routine consumes handoff artifacts."""

    library_reader: LibraryDigestReader
    watermark: RunWatermarkStore
    remarkable_sender: Any = field(default_factory=FakeRemarkableNotebookSender)
    chat_ping_sender: Any = field(default_factory=FakeGrokBotChatPingSender)
    notebook_title: str = "Morning Attention"
    handoff_dir: Path | None = None

    def run(
        self,
        *,
        notes: Sequence[ClaimNote],
        calendar_events: Sequence[Mapping[str, Any]] | None = None,
        deliver: bool = True,
        advance_watermark: bool = True,
        now: datetime | None = None,
        dry_run: bool = False,
    ) -> MorningAttentionRunResult:
        since = self.watermark.read()
        library_notes = self.library_reader.list_research_notes(since=since)
        library = LibraryDigestInput(
            resource_type_filter=LIBRARY_RESOURCE_TYPE_FILTER,
            since=since,
            notes=library_notes,
        )
        surface = build_morning_attention(
            notes,
            calendar_events=calendar_events,
            library=library,
            max_points=5,
        )

        # Empty day = silent (same as 6:40 handwritten pass).
        if not surface.points:
            written = None
            if advance_watermark and not dry_run:
                written = self.watermark.write(now or datetime.now(timezone.utc))
            manifest = {
                "silent": True,
                "reason": "empty_day",
                "point_count": 0,
                "deliver_remarkable": False,
                "deliver_grok_bot_ping": False,
                "channel_chat": "grok_bot",
                "fold_into_g10_calendar": False,
                "fold_into_research_from": False,
            }
            # Drop stale notebook / ping so Proey connectors do not re-push.
            self._clear_delivery_artifacts()
            self._write_manifest(manifest)
            return MorningAttentionRunResult(
                surface=surface,
                since=since,
                library_notes=library_notes,
                silent=True,
                handoff_manifest=manifest,
                watermark_written=written,
                dry_run=dry_run,
            )

        remarkable_payload = None
        chat_payload = None
        as_of = (now or datetime.now(timezone.utc)).astimezone(ET).strftime("%Y-%m-%d")
        # Default notebook title: "Morning Attention YYYY-MM-DD" (Nate may override).
        title = f"{self.notebook_title} {as_of}"
        md = morning_attention_markdown(surface, title=title)
        line = morning_attention_chat_line(surface, as_of=as_of)

        if deliver and not dry_run:
            remarkable = self.remarkable_sender.push(title=title, markdown=md)
            remarkable_payload = {
                "title": remarkable.title,
                "path": getattr(remarkable, "path", None),
                "http_status": getattr(remarkable, "http_status", None),
                "dry_run": getattr(remarkable, "dry_run", False),
            }
            chat = self.chat_ping_sender.send(body=line)
            chat_payload = {
                "channel": getattr(chat, "channel", "grok_bot"),
                "body": chat.body,
                "path": getattr(chat, "path", None),
                "http_status": getattr(chat, "http_status", None),
                "dry_run": getattr(chat, "dry_run", False),
            }

        manifest = {
            "silent": False,
            "point_count": len(surface.points),
            "notebook_title": title,
            "markdown_chars": len(md),
            "chat_ping_line": line,
            "channel_chat": "grok_bot",
            "deliver_remarkable": True,
            "deliver_grok_bot_ping": True,
            "fold_into_g10_calendar": False,
            "fold_into_research_from": False,
            "alter_tablet_555": False,
            "alter_tablet_610": False,
            "remarkable": remarkable_payload,
            "chat_ping": chat_payload,
        }
        self._write_manifest(manifest)

        written = None
        if advance_watermark and not dry_run:
            written = self.watermark.write(now or datetime.now(timezone.utc))

        return MorningAttentionRunResult(
            surface=surface,
            since=since,
            library_notes=library_notes,
            silent=False,
            remarkable=remarkable_payload,
            chat_ping=chat_payload,
            handoff_manifest=manifest,
            watermark_written=written,
            dry_run=dry_run,
        )

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        if self.handoff_dir is None:
            return
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        path = self.handoff_dir / "handoff.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def _clear_delivery_artifacts(self) -> None:
        """Remove notebook / Grok ping files; leave only silent handoff.json."""
        if self.handoff_dir is None:
            return
        for name in (
            "morning-attention.md",
            "notebook-title.txt",
            "chat-ping.txt",
        ):
            path = self.handoff_dir / name
            if path.is_file():
                path.unlink()


def intended_cron_expression() -> str:
    """Proey weekday 06:25 ET slot — documented for the Proey routine."""
    return f"{MORNING_ATTENTION_MINUTE_ET} {MORNING_ATTENTION_HOUR_ET} * * 1-5"


def is_intended_weekday_slot(when: datetime) -> bool:
    local = when.astimezone(ET) if when.tzinfo else when.replace(tzinfo=ET)
    return local.weekday() in MORNING_ATTENTION_WEEKDAYS
