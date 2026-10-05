"""Orchestrate morning-attention ops: LIBRARY since-last-run → build → deliver.

Cadence (Proey): weekdays ~06:25 America/New_York, after the 06:10 digest.
Does not change 5:55 / 6:10 tablet pushes. Does not fold into G10 Calendar or
Research From.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.claim_notes.delivery import (
    FakeChatPingSender,
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
    remarkable: dict[str, Any] | None = None
    chat_ping: dict[str, Any] | None = None
    watermark_written: datetime | None = None
    dry_run: bool = False


@dataclass
class MorningAttentionOps:
    """Injectable ops runner for tests and the weekday 6:25 ET schedule hook."""

    library_reader: LibraryDigestReader
    watermark: RunWatermarkStore
    remarkable_sender: Any = field(default_factory=FakeRemarkableNotebookSender)
    chat_ping_sender: Any = field(default_factory=FakeChatPingSender)
    notebook_title: str = "Morning attention"

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
        remarkable_payload = None
        chat_payload = None
        if deliver and not dry_run:
            as_of = (now or datetime.now(timezone.utc)).astimezone(ET).strftime("%Y-%m-%d")
            md = morning_attention_markdown(surface, title=self.notebook_title)
            remarkable = self.remarkable_sender.push(
                title=f"{self.notebook_title} {as_of}", markdown=md
            )
            remarkable_payload = {
                "title": remarkable.title,
                "path": getattr(remarkable, "path", None),
                "http_status": getattr(remarkable, "http_status", None),
                "dry_run": getattr(remarkable, "dry_run", False),
            }
            line = morning_attention_chat_line(surface, as_of=as_of)
            chat = self.chat_ping_sender.send(
                subject=f"Morning attention {as_of}", body=line
            )
            chat_payload = {
                "subject": chat.subject,
                "body": chat.body,
                "recipients": list(chat.recipients),
                "dry_run": chat.dry_run,
            }
        written = None
        if advance_watermark and not dry_run:
            written = self.watermark.write(now or datetime.now(timezone.utc))
        return MorningAttentionRunResult(
            surface=surface,
            since=since,
            library_notes=library_notes,
            remarkable=remarkable_payload,
            chat_ping=chat_payload,
            watermark_written=written,
            dry_run=dry_run,
        )


def intended_cron_expression() -> str:
    """Weekday 06:25 America/New_York — after 06:10 digest; does not touch 5:55/6:10."""
    return f"{MORNING_ATTENTION_MINUTE_ET} {MORNING_ATTENTION_HOUR_ET} * * 1-5"


def is_intended_weekday_slot(when: datetime) -> bool:
    local = when.astimezone(ET) if when.tzinfo else when.replace(tzinfo=ET)
    return local.weekday() in MORNING_ATTENTION_WEEKDAYS
