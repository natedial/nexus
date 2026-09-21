#!/usr/bin/env python3
"""Live PostgreSQL smoke test for parser document-identity upserts."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from src.config import get_settings
from src.storage.source_store import compute_document_hash


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live PostgreSQL smoke test for parsed_research identity upserts."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("RESEARCH_PARSER_DATABASE_URL")
        or os.getenv("NEXUS_DATABASE_URL"),
        help="PostgreSQL URL (or set NEXUS_DATABASE_URL)",
    )
    parser.add_argument(
        "--keep-row",
        action="store_true",
        help="Keep the temporary test row instead of deleting it",
    )
    return parser.parse_args()


def _build_record(
    *,
    document_id: str,
    source: str,
    document_name: str,
    document_hash: str,
    text: str,
) -> dict:
    return {
        "document_id": document_id,
        "parsed_data": {
            "full_text": text,
            "identity": {
                "document_id": document_id,
                "source": source,
                "source_date": "2026-04-14",
            },
        },
        "source_date": "2026-04-14",
        "source": source,
        "document_name": document_name,
        "document_title": "Codex Live Upsert Test",
        "document_link": None,
        "document_hash": document_hash,
    }


_UPSERT = """
INSERT INTO parsed_research (
    document_id, parsed_data, source_date, source, document_name,
    document_title, document_link, document_hash
) VALUES (
    %(document_id)s, %(parsed_data)s, %(source_date)s, %(source)s,
    %(document_name)s, %(document_title)s, %(document_link)s, %(document_hash)s
)
ON CONFLICT (document_id) DO UPDATE SET
    parsed_data = EXCLUDED.parsed_data,
    source_date = EXCLUDED.source_date,
    source = EXCLUDED.source,
    document_name = EXCLUDED.document_name,
    document_title = EXCLUDED.document_title,
    document_link = EXCLUDED.document_link,
    document_hash = EXCLUDED.document_hash
RETURNING id, trade_count, document_hash
"""


def main() -> int:
    args = parse_args()
    database_url = args.database_url or get_settings().database_url
    if not database_url:
        print("Missing database URL. Provide --database-url or set NEXUS_DATABASE_URL.")
        return 2

    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    document_id = f"codex-live-document-{suffix}"
    source = f"codex-live-upsert-test-{suffix}"
    document_name = f"codex-live-{suffix}.txt"
    text = f"Codex live upsert smoke test {suffix}"
    document_hash = compute_document_hash(text)
    cleanup_id: int | None = None

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            existing = conn.execute(
                "SELECT id FROM parsed_research WHERE document_id = %s LIMIT 1",
                (document_id,),
            ).fetchone()
            if existing:
                print(json.dumps({"status": "error", "error": "test_row_collision"}))
                return 1

            record1 = _build_record(
                document_id=document_id,
                source=source,
                document_name=document_name,
                document_hash=document_hash,
                text=text,
            )
            row1 = conn.execute(
                _UPSERT,
                {**record1, "parsed_data": Json(record1["parsed_data"])},
            ).fetchone()
            if not row1:
                print(json.dumps({"status": "error", "error": "first_upsert_failed"}))
                return 1
            cleanup_id = int(row1["id"])

            updated_text = f"{text} updated"
            updated_document_hash = compute_document_hash(updated_text)
            record2 = _build_record(
                document_id=document_id,
                source=source,
                document_name=document_name,
                document_hash=updated_document_hash,
                text=updated_text,
            )
            row2 = conn.execute(
                _UPSERT,
                {**record2, "parsed_data": Json(record2["parsed_data"])},
            ).fetchone()
            if not row2:
                print(json.dumps({"status": "error", "error": "second_upsert_failed"}))
                return 1

            fetched = conn.execute(
                """
                SELECT id, trade_count, document_id, document_hash, document_name, source
                FROM parsed_research WHERE id = %s
                """,
                (cleanup_id,),
            ).fetchone()
            if fetched is None:
                print(json.dumps({"status": "error", "error": "fetch_after_upsert_failed"}))
                return 1

            print(
                json.dumps(
                    {
                        "status": "ok",
                        "first_id": row1["id"],
                        "second_id": row2["id"],
                        "same_row": row1["id"] == row2["id"],
                        "trade_count_after_second_upsert": fetched.get("trade_count"),
                        "document_hash_after_second_upsert": fetched.get("document_hash"),
                        "hash_changed": fetched.get("document_hash") == updated_document_hash,
                        "document_name": document_name,
                        "source": source,
                    },
                    sort_keys=True,
                )
            )
            return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        if cleanup_id is not None and not args.keep_row and database_url:
            with psycopg.connect(database_url, row_factory=dict_row) as conn:
                conn.execute("DELETE FROM parsed_research WHERE id = %s", (cleanup_id,))
                verify = conn.execute(
                    "SELECT id FROM parsed_research WHERE id = %s LIMIT 1",
                    (cleanup_id,),
                ).fetchone()
                print(
                    json.dumps(
                        {
                            "cleanup_id": cleanup_id,
                            "cleanup_ok": verify is None,
                        },
                        sort_keys=True,
                    )
                )


if __name__ == "__main__":
    raise SystemExit(main())
