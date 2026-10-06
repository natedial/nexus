#!/usr/bin/env python3
"""CLI: morning-attention → Proey connector handoff (markdown + Grok Bot line).

Canonical ops path (Proey-owned, weekdays ~06:25 ET after 06:10):
  1) research_analyst ``export-dispatch-batch`` (argument_map documents since watermark)
  2) this script with ``--argument-map-json`` (or ``--analyst-batch-dir``) projects
     ClaimNodes → claim-note-v1 via ``project.py`` (Gerhard validators)
  3) handoff artifacts; Proey pushes reMarkable + Grok Bot ping

``--library-json`` is demoted — not the live claim source (see PR lock 2026-10-06).
Empty argument_map / no claims → silent (no notebook, no ping).
Does not modify 5:55 / 6:10 schedules.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
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
from src.claim_notes.project import (  # noqa: E402
    filter_argument_map_documents,
    load_argument_map_documents,
    project_argument_map_batch,
    resolve_analyst_batch_path,
)
from src.claim_notes.watermark import RunWatermarkStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--argument-map-json",
        help=(
            "Canonical live input: analyst export-dispatch-batch JSON "
            "({documents:[...]} with argument_map ClaimNodes)."
        ),
    )
    parser.add_argument(
        "--analyst-batch-dir",
        help=(
            "Thin MA flag: read latest.json (or --batch-file) from the analyst "
            "batch out dir produced by export-dispatch-batch."
        ),
    )
    parser.add_argument(
        "--batch-file",
        help="Filename inside --analyst-batch-dir (default: latest.json)",
    )
    parser.add_argument(
        "--since",
        help=(
            "ISO date or datetime — keep documents with source_date >= since "
            "(Proey since-watermark). Default: watermark date when set."
        ),
    )
    parser.add_argument(
        "--until",
        help="ISO date — keep documents with source_date <= until (inclusive).",
    )
    parser.add_argument(
        "--since-watermark",
        action="store_true",
        help="Filter argument_map documents by watermark date (source_date >= watermark).",
    )
    parser.add_argument(
        "--notes-jsonl",
        help="Optional claim-note JSONL (dev / offline; not required for live path)",
    )
    parser.add_argument(
        "--library-json",
        help=(
            "Demoted: LIBRARY Research Notes JSON for diagnostics only — "
            "does NOT project into claim notes. Prefer --argument-map-json."
        ),
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

    watermark = RunWatermarkStore(args.watermark)
    notes = _load_notes(args, watermark)
    library_reader = _build_library_reader(args)
    handoff_dir = _handoff_dir(args)
    remarkable, chat = _build_senders(args, handoff_dir)

    ops = MorningAttentionOps(
        library_reader=library_reader,
        watermark=watermark,
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
        "claim_note_count": len(notes),
        "library_note_count": len(result.library_notes),
        "remarkable": result.remarkable,
        "chat_ping": result.chat_ping,
        "handoff_manifest": result.handoff_manifest,
        "handoff_dir": str(handoff_dir) if handoff_dir else None,
        "watermark_written": (
            result.watermark_written.isoformat() if result.watermark_written else None
        ),
        "dry_run": result.dry_run,
        "claim_source": "argument_map",
    }
    print(json.dumps(payload, indent=2))
    return 0


def _load_notes(args, watermark: RunWatermarkStore) -> list:
    """Load claim notes from analyst argument_map (canonical) or offline JSONL."""
    if args.notes_jsonl:
        return list(load_claim_notes(args.notes_jsonl))

    map_path = _argument_map_path(args)
    if map_path is not None:
        docs = load_argument_map_documents(map_path)
        since, until = _since_until(args, watermark)
        docs = filter_argument_map_documents(docs, since=since, until=until)
        return project_argument_map_batch(docs)

    if args.library_json:
        # Demoted: accept flag for backwards CLI compat but do not project claims.
        return []

    token = (Config.NOTION_TOKEN or "").strip()
    if token:
        # Demoted Notion path — no claim projection.
        return []

    raise SystemExit(
        "Provide --argument-map-json or --analyst-batch-dir (canonical live path), "
        "or --notes-jsonl for offline fixtures. "
        "--library-json is demoted and does not supply claims."
    )


def _argument_map_path(args) -> Path | None:
    if args.argument_map_json:
        return Path(args.argument_map_json)
    if args.analyst_batch_dir:
        return Path(
            resolve_analyst_batch_path(
                args.analyst_batch_dir, batch_file=args.batch_file
            )
        )
    env_path = (
        getattr(Config, "MORNING_ARGUMENT_MAP_JSON", "") or ""
    ).strip()
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    batch_dir = (getattr(Config, "MORNING_ANALYST_BATCH_DIR", "") or "").strip()
    if batch_dir:
        return Path(resolve_analyst_batch_path(batch_dir, batch_file=args.batch_file))
    analyst_batch = (getattr(Config, "ANALYST_BATCH_PATH", "") or "").strip()
    if analyst_batch and Path(analyst_batch).is_file():
        return Path(analyst_batch)
    return None


def _since_until(args, watermark: RunWatermarkStore):
    since = _parse_bound(args.since) if args.since else None
    until = _parse_bound(args.until) if args.until else None
    if args.since_watermark and since is None:
        wm = watermark.read()
        if wm is not None:
            since = wm
    return since, until


def _parse_bound(raw: str) -> date | datetime:
    text = raw.strip()
    if "T" in text or " " in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    return date.fromisoformat(text[:10])


def _handoff_dir(args) -> Path | None:
    raw = (args.handoff_dir or getattr(Config, "MORNING_HANDOFF_DIR", "") or "").strip()
    return Path(raw) if raw else None


def _build_library_reader(args):
    """Demoted LIBRARY reader — diagnostics / counts only; never claim source."""
    if args.library_json:
        rows = json.loads(Path(args.library_json).read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("notes") or rows.get("research_notes") or []
        notes = [LibraryResearchNote.model_validate(r) for r in rows]
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
