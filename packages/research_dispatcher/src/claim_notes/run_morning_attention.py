#!/usr/bin/env python3
"""CLI: run morning-attention ops (LIBRARY since-last-run → deliver).

Intended cadence: weekdays 06:25 America/New_York via schedule_morning_attention.sh.
Does not modify 5:55 / 6:10 tablet pushes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python src/claim_notes/run_morning_attention.py` from package root.
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from config import Config  # noqa: E402
from src.claim_notes.delivery import (  # noqa: E402
    FakeChatPingSender,
    FakeRemarkableNotebookSender,
    FileRemarkableNotebookSender,
    HttpRemarkableNotebookSender,
    SmtpChatPingSender,
)
from src.claim_notes.load import load_claim_notes  # noqa: E402
from src.claim_notes.notion_library import NotionLibraryDigestReader  # noqa: E402
from src.claim_notes.ops import MorningAttentionOps  # noqa: E402
from src.claim_notes.project import project_argument_map_batch  # noqa: E402
from src.claim_notes.watermark import RunWatermarkStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--notes-jsonl",
        help="Claim-note JSONL (optional if --argument-map-json is set)",
    )
    parser.add_argument(
        "--argument-map-json",
        help="Dispatch/analyst documents JSON with argument_map arrays",
    )
    parser.add_argument(
        "--watermark",
        default=Config.MORNING_WATERMARK_PATH
        or str(PACKAGE_ROOT / "state" / "morning_attention_last_run.json"),
        help="Path to since-last-run watermark file",
    )
    parser.add_argument(
        "--remarkable-drop-dir",
        default="",
        help="Write own-surface markdown notebook here (Remarkdown drop)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build surface only; skip delivery and watermark advance",
    )
    parser.add_argument(
        "--fake-delivery",
        action="store_true",
        help="Use in-memory delivery fakes (no SMTP / HTTP)",
    )
    args = parser.parse_args(argv)

    notes = _load_notes(args.notes_jsonl, args.argument_map_json)
    library_reader = NotionLibraryDigestReader(
        token=Config.NOTION_TOKEN or None,
        database_id=Config.NOTION_LIBRARY_DATABASE_ID,
    )
    remarkable = _build_remarkable(args)
    chat = _build_chat(args)
    ops = MorningAttentionOps(
        library_reader=library_reader,
        watermark=RunWatermarkStore(args.watermark),
        remarkable_sender=remarkable,
        chat_ping_sender=chat,
    )
    calendar_events = _maybe_calendar()
    result = ops.run(
        notes=notes,
        calendar_events=calendar_events,
        deliver=not args.dry_run,
        advance_watermark=not args.dry_run,
        dry_run=args.dry_run,
    )
    payload = {
        "points": [p.model_dump() for p in result.surface.points],
        "delivery": result.surface.delivery.model_dump(),
        "since": result.since.isoformat() if result.since else None,
        "library_note_count": len(result.library_notes),
        "remarkable": result.remarkable,
        "chat_ping": result.chat_ping,
        "watermark_written": (
            result.watermark_written.isoformat() if result.watermark_written else None
        ),
        "dry_run": result.dry_run,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _load_notes(notes_jsonl: str | None, argument_map_json: str | None):
    if notes_jsonl:
        return load_claim_notes(notes_jsonl)
    if argument_map_json:
        data = json.loads(Path(argument_map_json).read_text(encoding="utf-8"))
        docs = data["documents"] if isinstance(data, dict) and "documents" in data else data
        return project_argument_map_batch(docs)
    raise SystemExit("Provide --notes-jsonl or --argument-map-json")


def _build_remarkable(args):
    if args.fake_delivery or args.dry_run:
        return FakeRemarkableNotebookSender()
    push_url = (Config.REMARKABLE_PUSH_URL or "").strip()
    if push_url:
        return HttpRemarkableNotebookSender(
            url=push_url,
            token=Config.REMARKABLE_PUSH_TOKEN or None,
        )
    drop = (args.remarkable_drop_dir or Config.REMARKABLE_DROP_DIR or "").strip()
    if drop:
        return FileRemarkableNotebookSender(drop)
    return FakeRemarkableNotebookSender()


def _build_chat(args):
    if args.fake_delivery or args.dry_run:
        return FakeChatPingSender()
    to_email = (Config.CHAT_PING_TO or Config.EMAIL_TO or "").strip()
    if not (Config.SMTP_USERNAME and Config.SMTP_PASSWORD and Config.EMAIL_FROM and to_email):
        return FakeChatPingSender()
    return SmtpChatPingSender(
        smtp_server=Config.SMTP_SERVER,
        smtp_port=Config.SMTP_PORT,
        username=Config.SMTP_USERNAME,
        password=Config.SMTP_PASSWORD,
        from_email=Config.EMAIL_FROM,
        to_email=to_email,
    )


def _maybe_calendar():
    try:
        from src.database import DatabaseClient

        db = DatabaseClient()
        return db.query_economic_events() or []
    except Exception:
        return []


if __name__ == "__main__":
    raise SystemExit(main())
