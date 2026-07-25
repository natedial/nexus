"""Daily morning research orchestration."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import structlog

from morning_research.codex_runner import CodexRunError, load_prompt, run_codex
from morning_research.config import Settings, get_settings
from morning_research.drive_pull import DrivePuller
from morning_research.models import RunReceipt
from morning_research.notion_client import NotionClient, NotionError
from morning_research.prefilter import prefilter
from morning_research.qc import run_qc
from morning_research.state import (
    load_state,
    mark_documents_processed,
    mark_run_successful,
    processing_window,
    save_state,
)
from morning_research.supabase_store import persist_run

logger = structlog.get_logger()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_dry_run_outputs(
    work_dir: Path,
    *,
    run_id: str,
    candidates,
    window_start: datetime,
    window_end: datetime,
    used_fallback: bool,
) -> None:
    filler = " ".join(["analysis"] * 450)
    (work_dir / "draft.md").write_text(
        (
            "Provided by Codex\n\n"
            f"# Research from dry-run {run_id}\n\n"
            f"# **Executive Takeaways**\n\n{filler}\n\n"
            "# **What Changed Versus Recent Research**\n\nNone in dry run.\n\n"
            "# **Changes in Views, Forecasts, or Recommendations**\n\nNone.\n\n"
            "# **Key Themes and Evidence**\n\nNone.\n\n"
            "# **Contrarian Views and Disagreements**\n\nNone.\n\n"
            "# **Watchlist**\n\n| Item | Evidence | Horizon |\n| --- | --- | --- |\n"
            "| n/a | n/a | n/a |\n\n"
            "# **Report Index**\n\nDry run stub.\n"
        ),
        encoding="utf-8",
    )
    (work_dir / "receipt.json").write_text(
        json.dumps(
            {
                "page_title": f"Research dry-run {run_id}",
                "documents_analyzed": [c.file_id for c in candidates],
                "window_start": _iso(window_start),
                "window_end": _iso(window_end),
                "used_fallback_window": used_fallback,
                "alerts": ["dry_run"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def run_daily(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    now = _utc_now()
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    work_dir = settings.resolved_work_dir() / run_id
    state_path = settings.resolved_state_path()
    prior_dir = work_dir / "prior_notes"
    extractions_dir = work_dir / "extractions"
    for path in (work_dir, prior_dir, extractions_dir):
        path.mkdir(parents=True, exist_ok=True)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    )
    log = logger.bind(run_id=run_id)
    log.info("Starting morning research run", work_dir=str(work_dir))

    state = load_state(state_path)
    window_start, used_fallback = processing_window(state, now=now)
    window_end = now
    (work_dir / "state_snapshot.json").write_text(
        json.dumps(
            {
                "last_successful_run": state.last_successful_run,
                "processed_document_count": len(state.processed_documents),
                "window_start": _iso(window_start),
                "window_end": _iso(window_end),
                "used_fallback_window": used_fallback,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        puller = DrivePuller(settings.google_credentials_path, settings.google_drive_folder_id)
        pull_result = puller.pull(
            window_start=window_start,
            work_dir=work_dir,
            state=state,
        )
        kept, excluded = prefilter(
            pull_result.candidates, min_pdf_bytes=settings.min_pdf_bytes
        )
        # Refresh manifest with prefilter outcomes
        manifest_path = work_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = {"candidates": [], "skipped_duplicates": pull_result.skipped_duplicates}
        manifest["kept"] = [c.to_manifest_dict() for c in kept]
        manifest["excluded"] = [c.to_manifest_dict() for c in excluded]
        manifest["window_start"] = _iso(window_start)
        manifest["window_end"] = _iso(window_end)
        manifest["used_fallback_window"] = used_fallback
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        log.error("Drive pull failed", error=str(exc))
        return 1

    if not kept:
        log.info("No qualifying candidates; no-op success")
        state = mark_run_successful(state, now=now)
        save_state(state_path, state)
        return 0

    try:
        notion = NotionClient(
            settings.notion_token,
            area_page_id=settings.notion_area_page_id,
        )
        notion.fetch_prior_notes_to_markdown(
            settings.notion_database_id, prior_dir, limit=5
        )
    except Exception as exc:
        log.error("Failed to fetch prior Notion notes", error=str(exc))
        return 1

    if settings.dry_run:
        log.info("DRY_RUN set; writing stub draft/receipt and skipping Codex/Notion")
        _write_dry_run_outputs(
            work_dir,
            run_id=run_id,
            candidates=kept,
            window_start=window_start,
            window_end=window_end,
            used_fallback=used_fallback,
        )
    else:
        try:
            prompt = load_prompt(settings.prompt_path, work_dir=work_dir)
            prompt = prompt.replace("{{PACKAGE_ROOT}}", str(settings.package_root))
            prompt = prompt.replace("{{AGENTS_PATH}}", str(settings.agents_path))
            run_codex(
                codex_bin=settings.codex_bin,
                prompt=prompt,
                work_dir=work_dir,
                package_root=settings.package_root,
                timeout_seconds=settings.codex_timeout_seconds,
                model=settings.codex_model,
            )
        except CodexRunError as exc:
            log.error("Codex failed", error=str(exc), stderr=getattr(exc, "stderr", ""))
            return 1

    qc = run_qc(work_dir)
    for warning in qc.warnings:
        log.warning("QC warning", warning=warning)
    if not qc.ok:
        log.error("QC failed", errors=qc.errors)
        return 1

    receipt_raw = json.loads((work_dir / "receipt.json").read_text(encoding="utf-8"))
    receipt = RunReceipt.from_dict(receipt_raw)
    draft = (work_dir / "draft.md").read_text(encoding="utf-8")

    if settings.dry_run:
        notion_page_id = "dry-run"
        notion_url = str(work_dir / "draft.md")
    else:
        try:
            notion_page_id = notion.publish_draft(
                database_id=settings.notion_database_id,
                draft_markdown=draft,
                fallback_title=receipt.page_title or f"Research {run_id}",
            )
            notion_url = f"https://www.notion.so/{notion_page_id.replace('-', '')}"
        except NotionError as exc:
            log.error("Notion publish failed", error=str(exc))
            return 1

    if settings.dry_run:
        # Dry runs exercise Drive/Notion-fetch/QC only. Never advance the
        # durable ledger — otherwise real docs get marked processed without
        # Codex analysis and are skipped on the next live run.
        log.info(
            "Morning research dry run succeeded (state not updated)",
            notion_page_id=notion_page_id,
            notion_url=notion_url,
            page_title=receipt.page_title,
            documents=len(kept),
            work_dir=str(work_dir),
        )
        return 0

    try:
        persist_run(
            settings,
            run_id=run_id,
            receipt=receipt,
            notion_page_id=notion_page_id,
            candidates=kept,
            work_dir=work_dir,
        )
    except Exception as exc:
        log.warning("Supabase persistence failed", error=str(exc))

    analyzed_ids = set(receipt.documents_analyzed) or {c.file_id for c in kept}
    meta = {
        doc.file_id: {
            "file_name": doc.name,
            "content_hash": doc.content_hash,
            "publication_date": None,
            "drive_modified_timestamp": doc.modified_time.isoformat(),
        }
        for doc in kept
        if doc.file_id in analyzed_ids
    }
    state = mark_documents_processed(state, meta, now=now)
    state = mark_run_successful(state, notion_page_id=notion_page_id, now=now)
    save_state(state_path, state)

    log.info(
        "Morning research run succeeded",
        notion_page_id=notion_page_id,
        notion_url=notion_url,
        page_title=receipt.page_title,
        documents=len(meta),
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if argv in (["-h"], ["--help"]):
        print("Usage: python -m morning_research")
        raise SystemExit(0)
    raise SystemExit(run_daily())


if __name__ == "__main__":
    main()
