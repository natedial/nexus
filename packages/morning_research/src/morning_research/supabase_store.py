"""Deterministic Supabase persistence for digest runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from morning_research.config import Settings
from morning_research.models import CandidateDoc, RunReceipt

logger = structlog.get_logger()


def _client(settings: Settings):
    if not settings.supabase_enabled:
        return None
    try:
        from supabase import create_client
    except ImportError:
        logger.warning("supabase package not installed; skipping persistence")
        return None
    return create_client(settings.supabase_url, settings.supabase_key)


def persist_run(
    settings: Settings,
    *,
    run_id: str,
    receipt: RunReceipt,
    notion_page_id: str,
    candidates: list[CandidateDoc],
    work_dir: Path,
    status: str = "success",
) -> None:
    client = _client(settings)
    if client is None:
        logger.info("Supabase not configured; skipping upsert")
        return

    alerts = list(receipt.raw.get("alerts") or [])
    run_row = {
        "run_id": run_id,
        "window_start": receipt.window_start,
        "window_end": receipt.window_end,
        "used_fallback_window": receipt.used_fallback_window,
        "notion_page_id": notion_page_id,
        "page_title": receipt.page_title,
        "status": status,
        "document_count": len(receipt.documents_analyzed),
        "alerts": alerts,
    }
    client.table("research_digest_runs").upsert(run_row, on_conflict="run_id").execute()

    by_id = {doc.file_id: doc for doc in candidates}
    for file_id in receipt.documents_analyzed:
        doc = by_id.get(file_id)
        doc_row: dict[str, Any] = {
            "run_id": run_id,
            "file_id": file_id,
            "file_name": doc.name if doc else file_id,
            "content_hash": doc.content_hash if doc else None,
            "publication_date": None,
            "drive_modified_timestamp": doc.modified_time.isoformat() if doc else None,
        }
        client.table("research_digest_documents").upsert(
            doc_row, on_conflict="run_id,file_id"
        ).execute()

        extraction_path_json = work_dir / "extractions" / f"{file_id}.json"
        extraction_path_md = work_dir / "extractions" / f"{file_id}.md"
        payload: dict[str, Any] | None = None
        raw_text: str | None = None
        if extraction_path_json.exists():
            payload = json.loads(extraction_path_json.read_text(encoding="utf-8"))
        elif extraction_path_md.exists():
            raw_text = extraction_path_md.read_text(encoding="utf-8")
        if payload is not None or raw_text is not None:
            client.table("research_digest_extractions").upsert(
                {
                    "run_id": run_id,
                    "file_id": file_id,
                    "extraction": payload,
                    "extraction_markdown": raw_text,
                },
                on_conflict="run_id,file_id",
            ).execute()

    logger.info("Persisted digest run to Supabase", run_id=run_id)
