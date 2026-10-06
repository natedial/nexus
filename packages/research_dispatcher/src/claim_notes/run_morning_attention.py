#!/usr/bin/env python3
"""CLI: morning-attention → Proey connector handoff (markdown + Grok Bot line).

Canonical ops path (Proey-owned, weekdays ~06:25 ET after 06:10):
  --library-json (Research Notes since last run) projects into claim notes,
  then this script writes handoff artifacts; Proey pushes reMarkable + Grok Bot
  ping with the same connectors as the 5:55 / 6:10 briefs.

Live path needs **no fixtures**. Empty library → silent (no notebook, no ping).
Does not modify 5:55 / 6:10 schedules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from config import Config  # noqa: E402
from src.claim_notes.delivery import (  # noqa: E402
    FakeGrokBotChatPingSender,
    FakeRemarkableNotebookSender,
    HandoffGrokBotChatPingSender,
    HandoffRemarkableNotebookSender,
    HttpGrokBotChatPingSender,
    HttpRemarkableNotebookSender,
)
from src.claim_notes.library import (  # noqa: E402
    FakeLibraryDigestReader,
    LibraryResearchNote,
    PrefilteredLibraryDigestReader,
)
from src.claim_notes.load import load_claim_notes  # noqa: E402
from src.claim_notes.notion_library import NotionLibraryDigestReader  # noqa: E402
from src.claim_notes.ops import MorningAttentionOps  # noqa: E402
from src.claim_notes.project import project_argument_map_batch  # noqa: E402
from src.claim_notes.watermark import RunWatermarkStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-json",
        help=(
            "Canonical live input: LIBRARY Research Notes JSON already filtered "
            "to Resource Type=Research Note and since last run (Proey inject). "
            "Projects into claim notes — no fixture required."
        ),
    )
    parser.add_argument(
        "--notes-jsonl",
        help="Optional claim-note JSONL (dev / offline; not required for live path)",
    )
    parser.add_argument(
        "--argument-map-json",
        help="Optional argument_map documents JSON (dev / offline)",
    )
    parser.add_argument(
        "--watermark",
        default=Config.MORNING_WATERMARK_PATH
        or str(PACKAGE_ROOT / "state" / "morning_attention_last_run.json"),
    )
    parser.add_argument(
        "--handoff-dir",
        default="",
        help="Canonical output dir for Proey connectors (md + grok ping + handoff.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build only; skip delivery writes and watermark advance",
    )
    parser.add_argument(
        "--fake-delivery",
        action="store_true",
        help="In-memory fakes (tests / local dry)",
    )
    args = parser.parse_args(argv)

    notes = _load_notes(args)
    library_reader = _build_library_reader(args)
    handoff_dir = _handoff_dir(args)
    remarkable, chat = _build_senders(args, handoff_dir)

    ops = MorningAttentionOps(
        library_reader=library_reader,
        watermark=RunWatermarkStore(args.watermark),
        remarkable_sender=remarkable,
        chat_ping_sender=chat,
        handoff_dir=handoff_dir,
    )
    result = ops.run(
        notes=notes,
        calendar_events=_maybe_calendar(),
        deliver=not args.dry_run,
        advance_watermark=not args.dry_run,
        dry_run=args.dry_run,
    )
    payload = {
        "silent": result.silent,
        "points": [p.model_dump() for p in result.surface.points],
        "delivery": result.surface.delivery.model_dump(),
        "since": result.since.isoformat() if result.since else None,
        "library_note_count": len(result.library_notes),
        "remarkable": result.remarkable,
        "chat_ping": result.chat_ping,
        "handoff_manifest": result.handoff_manifest,
        "handoff_dir": str(handoff_dir) if handoff_dir else None,
        "watermark_written": (
            result.watermark_written.isoformat() if result.watermark_written else None
        ),
        "dry_run": result.dry_run,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _load_notes(args) -> list:
    """Optional claim-note files. Live path may omit these (LIBRARY projects)."""
    if args.notes_jsonl:
        return list(load_claim_notes(args.notes_jsonl))
    if args.argument_map_json:
        data = json.loads(Path(args.argument_map_json).read_text(encoding="utf-8"))
        docs = (
            data["documents"]
            if isinstance(data, dict) and "documents" in data
            else data
        )
        return project_argument_map_batch(docs)
    if args.library_json:
        # Ops projects LIBRARY → claim notes when notes is empty.
        return []
    token = (Config.NOTION_TOKEN or "").strip()
    if token:
        # Live Notion reader supplies LIBRARY; ops projects when notes empty.
        return []
    raise SystemExit(
        "Provide --library-json (canonical live path), or --notes-jsonl / "
        "--argument-map-json for offline fixtures"
    )


def _handoff_dir(args) -> Path | None:
    raw = (args.handoff_dir or getattr(Config, "MORNING_HANDOFF_DIR", "") or "").strip()
    return Path(raw) if raw else None


def _build_library_reader(args):
    if args.library_json:
        rows = json.loads(Path(args.library_json).read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("notes") or rows.get("research_notes") or []
        notes = [LibraryResearchNote.model_validate(r) for r in rows]
        # Already filtered by Proey — do not re-apply watermark since-bound.
        return PrefilteredLibraryDigestReader(notes)
    token = (Config.NOTION_TOKEN or "").strip()
    if token:
        return NotionLibraryDigestReader(
            token=token,
            database_id=Config.NOTION_LIBRARY_DATABASE_ID,
        )
    return FakeLibraryDigestReader([])


def _build_senders(args, handoff_dir: Path | None):
    if args.fake_delivery or args.dry_run:
        return FakeRemarkableNotebookSender(), FakeGrokBotChatPingSender()
    if handoff_dir is not None:
        return (
            HandoffRemarkableNotebookSender(handoff_dir),
            HandoffGrokBotChatPingSender(handoff_dir),
        )
    remarkable = FakeRemarkableNotebookSender()
    push_url = (Config.REMARKABLE_PUSH_URL or "").strip()
    if push_url:
        remarkable = HttpRemarkableNotebookSender(
            url=push_url, token=Config.REMARKABLE_PUSH_TOKEN or None
        )
    elif (Config.REMARKABLE_DROP_DIR or "").strip():
        remarkable = HandoffRemarkableNotebookSender(Config.REMARKABLE_DROP_DIR)

    grok_url = (getattr(Config, "GROK_BOT_PING_URL", "") or "").strip()
    if grok_url:
        chat = HttpGrokBotChatPingSender(
            url=grok_url, token=getattr(Config, "GROK_BOT_PING_TOKEN", None)
        )
    else:
        chat = FakeGrokBotChatPingSender()
    return remarkable, chat


def _maybe_calendar():
    try:
        from src.database import DatabaseClient

        return DatabaseClient().query_economic_events() or []
    except Exception:
        return []


if __name__ == "__main__":
    raise SystemExit(main())
