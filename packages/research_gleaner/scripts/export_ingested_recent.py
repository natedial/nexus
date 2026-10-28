#!/usr/bin/env python3
"""Read-only export of recently ingested Nexus research to a JSON file.

Selects rows from ``parsed_research`` whose ``created_at`` (parser insert time)
falls inside the window, and writes them atomically so a reader never sees a
half-written file. On any failure the previous file is left untouched and the
process exits non-zero.

Credentials come from the Nexus ``.env`` files via ``research_gleaner.env``;
they are never printed, logged or written to the output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

DEFAULT_OUT = PACKAGE_ROOT / "ingested_recent.json"
DEFAULT_WINDOW_HOURS = 48
EXCERPT_CHARS = 4000
# Pull a bounded prefix from Postgres; some documents exceed 1M characters.
FETCH_PREFIX_CHARS = 30000

QUERY = """
SELECT
    p.id,
    p.document_id,
    p.document_title,
    p.document_name,
    COALESCE(p.publisher, p.source, p.parsed_data->'identity'->>'source') AS publisher,
    p.area,
    p.region,
    p.asset_focus,
    p.created_at,
    p.source_date,
    p.document_link,
    left(p.parsed_data->>'full_text', %(prefix)s) AS text_prefix,
    length(p.parsed_data->>'full_text') AS full_text_chars
FROM parsed_research p
WHERE p.created_at >= now() - make_interval(hours => %(hours)s)
ORDER BY p.created_at DESC, p.id DESC
"""

_PAGE_MARKER = re.compile(r"^\s*---\s*PAGE\s+\d+\s*---\s*$", re.MULTILINE)
_HEADING = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def clean_title(raw: str | None) -> str | None:
    """Turn ``2026-10-28_DB__Some_title_DB`` into ``Some title``."""
    if not raw:
        return None
    name = _DATE_PREFIX.sub("", raw)
    code, sep, rest = name.partition("__")
    if sep:
        # A short all-caps token is a broker code; anything longer is title text.
        if re.fullmatch(r"[A-Z]{1,5}", code):
            name = rest
            name = re.sub(rf"_{re.escape(code)}$", "", name)
        else:
            name = f"{code.replace('_', ' ')}: {rest}"
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip() or None


def clean_excerpt(text: str, limit: int) -> str:
    text = _PAGE_MARKER.sub("", text)
    text = _HEADING.sub("", text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.8:
        cut = cut[:space]
    return cut.rstrip() + "…"


def iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().isoformat(timespec="seconds")
    return value.isoformat()


def build_document(row: dict, excerpt_chars: int) -> dict:
    cleaned = clean_excerpt(row["text_prefix"] or "", excerpt_chars)
    truncated = (
        cleaned.endswith("…")
        or (row["full_text_chars"] or 0) > FETCH_PREFIX_CHARS
    )
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "title": clean_title(row["document_title"]) or row["document_title"],
        "raw_title": row["document_title"],
        "publisher": row["publisher"],
        "area": row["area"],
        "region": row["region"],
        "asset_focus": row["asset_focus"],
        "ingested_at": iso(row["created_at"]),
        "publication_date": iso(row["source_date"]),
        "url": row["document_link"],
        "file_name": row["document_name"],
        "text": cleaned,
        "text_truncated": truncated,
        "full_text_chars": row["full_text_chars"],
    }


def fetch(window_hours: float, excerpt_chars: int) -> list[dict]:
    from research_gleaner.env import load_environment

    load_environment()
    url = os.environ.get("NEXUS_DATABASE_URL")
    if not url:
        raise RuntimeError("NEXUS_DATABASE_URL is not set")

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        url,
        options="-c default_transaction_read_only=on",
        connect_timeout=10,
        row_factory=dict_row,
    ) as conn:
        conn.read_only = True
        rows = conn.execute(
            QUERY, {"hours": window_hours, "prefix": FETCH_PREFIX_CHARS}
        ).fetchall()
    return [build_document(r, excerpt_chars) for r in rows]


def write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def safe_error(exc: BaseException) -> str:
    """Describe an error without leaking a connection string."""
    msg = re.sub(r"\w+://\S+", "<url>", str(exc)).strip()
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=DEFAULT_WINDOW_HOURS,
                        help="ingestion window in hours (default: %(default)s)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="output JSON path (default: %(default)s)")
    parser.add_argument("--excerpt-chars", type=int, default=EXCERPT_CHARS)
    args = parser.parse_args(argv)

    try:
        documents = fetch(args.hours, args.excerpt_chars)
        window = int(args.hours) if float(args.hours).is_integer() else args.hours
        payload = {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "window_hours": window,
            "count": len(documents),
            "documents": documents,
        }
        write_atomic(args.out, payload)
    except Exception as exc:  # noqa: BLE001 - top-level guard; keep last good file
        print(f"export_ingested_recent: FAILED: {safe_error(exc)}; "
              f"previous output left untouched", file=sys.stderr)
        return 1

    print(f"export_ingested_recent: wrote {len(documents)} documents to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
