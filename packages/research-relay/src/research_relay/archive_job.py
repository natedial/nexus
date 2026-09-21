from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from research_relay.archive_format import (
    archive_html_document,
    archive_html_name,
    archive_pdf_name,
)
from research_relay.attachments import AttachmentDecision, AttachmentPolicy
from research_relay.config import AppConfig
from research_relay.drive_archive import upload_html as _upload_html
from research_relay.drive_archive import upload_pdf as _upload_pdf
from research_relay.drive_archive import upload_pdf_as_gdoc as _upload_gdoc
from research_relay.domain import domain_allowed
from research_relay.exceptions import DriveAuthError, TemporaryRelayError
from research_relay.intake_contract import bundle_id_for_relay_key
from research_relay.intake_handoff import maybe_write_intake_handoff
from research_relay.ledger import ArchiveRow, Ledger
from research_relay.reconstruct import Reconstruction, ReconstructionSettings, parse_rfc822, reconstruct_message

log = logging.getLogger("research_relay")


@dataclass
class ArchiveRunResult:
    dry_run: bool = False
    attempted: int = 0
    completed: int = 0
    temporary_failures: int = 0
    operational_failures: int = 0
    unrecoverable: int = 0
    notes: list[str] = field(default_factory=list)

    def exit_code(self) -> int:
        if self.operational_failures:
            return 1
        return 0


@dataclass
class EnqueueRecentResult:
    dry_run: bool = False
    scanned: int = 0
    enqueued: int = 0
    skipped_existing: int = 0
    skipped_domain: int = 0
    skipped_other: int = 0
    skipped_limit: int = 0
    notes: list[str] = field(default_factory=list)


def reconstruction_settings(cfg: AppConfig, hmac_key: bytes) -> ReconstructionSettings:
    return ReconstructionSettings(
        proton_from=cfg.proton.from_address,
        reply_to=cfg.proton.reply_to,
        private_address=cfg.relay.private_address,
        hmac_key=hmac_key,
        message_id_domain=cfg.relay.message_id_domain,
        attachment_policy=AttachmentPolicy(
            max_individual_bytes=cfg.attachments.max_individual_bytes,
            max_combined_bytes=cfg.attachments.max_combined_bytes,
            blocked_extensions=cfg.attachments.blocked_extensions,
            allowed_extensions=cfg.attachments.allowed_extensions,
            on_prohibited=cfg.attachments.on_prohibited,
            private_address=cfg.relay.private_address,
        ),
    )


def enqueue_proton_archive(
    cfg: AppConfig,
    ledger: Ledger,
    gmail_msgid: str,
    *,
    original: EmailMessage,
    reconstructed: Reconstruction,
) -> None:
    if not cfg.archive.enabled:
        return
    kind, names = _plan(cfg, original, reconstructed)
    message_id = str(original.get("Message-ID") or "").strip()
    ledger.enqueue_archive(
        gmail_msgid,
        message_id=message_id,
        kind=kind,
        expected_names=names,
    )
    log.info("archive enqueued key=%s kind=%s", gmail_msgid[-24:], kind)


def enqueue_recent_archives(
    cfg: AppConfig,
    *,
    imap: object,
    hmac_key: bytes,
    hours: int | None = None,
    since: datetime | None = None,
    limit: int | None = None,
    dry_run: bool,
    ledger: Ledger | None = None,
) -> EnqueueRecentResult:
    result = EnqueueRecentResult(dry_run=dry_run)
    if not cfg.archive.enabled:
        result.notes.append("archive disabled")
        return result
    own = ledger is None
    store = ledger or Ledger(cfg.paths.ledger)
    try:
        keys = imap.collect_recent_native(hours=hours, since=since)
        settings = reconstruction_settings(cfg, hmac_key)
        for key in keys:
            result.scanned += 1
            existing = store.get_archive(key)
            if existing is not None:
                result.skipped_existing += 1
                continue
            if limit is not None and result.enqueued >= max(0, int(limit)):
                result.skipped_limit += 1
                continue
            try:
                raw = imap.fetch_message(key)
                original = parse_rfc822(raw)
            except Exception:
                result.skipped_other += 1
                continue
            from_header = str(original.get("From") or "")
            if not domain_allowed(from_header, cfg.relay.allowed_domains, cfg.relay.allow_subdomains):
                result.skipped_domain += 1
                continue
            try:
                reconstructed = reconstruct_message(original, gmail_msgid=key, settings=settings)
            except Exception:
                result.skipped_other += 1
                continue
            kind, names = _plan(cfg, original, reconstructed)
            note = f"{key} kind={kind} files={len(names) or 1}"
            if dry_run:
                result.notes.append(f"would enqueue {note}")
                result.enqueued += 1
                continue
            enqueue_proton_archive(
                cfg, store, key, original=original, reconstructed=reconstructed
            )
            result.notes.append(f"enqueued {note}")
            result.enqueued += 1
        return result
    finally:
        if own:
            store.close()


def process_archives(
    cfg: AppConfig,
    *,
    imap: object,
    hmac_key: bytes,
    dry_run: bool,
    ledger: Ledger | None = None,
    access_token: str = "",
    upload_pdf=_upload_pdf,
    upload_gdoc=_upload_gdoc,
    upload_html=_upload_html,
    force_key: str | None = None,
) -> ArchiveRunResult:
    result = ArchiveRunResult(dry_run=dry_run)
    if not cfg.archive.enabled:
        return result
    own = ledger is None
    store = ledger or Ledger(cfg.paths.ledger)
    try:
        if force_key:
            store.clear_archive_ids(force_key)
            row = store.get_archive(force_key)
            rows = [row] if row is not None else []
        else:
            rows = store.list_incomplete(limit=cfg.archive.max_retries_per_run)
        if dry_run:
            for row in rows:
                result.notes.append(f"would archive {row.gmail_msgid} missing={_missing(row)}")
                result.attempted += 1
            return result
        settings = reconstruction_settings(cfg, hmac_key)
        for row in rows:
            result.attempted += 1
            log.info("archive start key=%s kind=%s", row.gmail_msgid[-24:], row.kind)
            try:
                _process_row(
                    cfg,
                    row=row,
                    imap=imap,
                    settings=settings,
                    ledger=store,
                    access_token=access_token,
                    upload_pdf=upload_pdf,
                    upload_gdoc=upload_gdoc,
                    upload_html=upload_html,
                )
                fresh = store.get_archive(row.gmail_msgid)
                if store.archive_is_complete(fresh):
                    result.completed += 1
                    log.info("archive done key=%s", row.gmail_msgid[-24:])
                    if cfg.intake.enabled and fresh is not None and fresh.kind in {
                        "pdfs",
                        "html",
                    }:
                        _maybe_write_intake_handoff(
                            cfg,
                            store,
                            row=fresh,
                            imap=imap,
                            settings=settings,
                        )
                elif fresh and fresh.unrecoverable:
                    result.unrecoverable += 1
                    log.warning("archive unrecoverable key=%s", row.gmail_msgid[-24:])
            except DriveAuthError as exc:
                result.operational_failures += 1
                store.record_archive_error(row.gmail_msgid, str(exc))
                log.warning("archive drive auth failed key=%s", row.gmail_msgid[-24:])
                break
            except TemporaryRelayError as exc:
                text = str(exc)
                if "not found" in text.lower():
                    became = store.record_find_miss(
                        row.gmail_msgid, threshold=cfg.archive.find_failure_threshold
                    )
                    if became:
                        result.unrecoverable += 1
                    else:
                        result.temporary_failures += 1
                else:
                    result.temporary_failures += 1
                    store.record_archive_error(row.gmail_msgid, text)
            except Exception as exc:
                result.temporary_failures += 1
                store.record_archive_error(row.gmail_msgid, exc.__class__.__name__)
                log.warning(
                    "archive failed key=%s error=%s",
                    row.gmail_msgid[-24:],
                    exc.__class__.__name__,
                )
        return result
    finally:
        if own:
            store.close()


def _process_row(
    cfg: AppConfig,
    *,
    row: ArchiveRow,
    imap: object,
    settings: ReconstructionSettings,
    ledger: Ledger,
    access_token: str,
    upload_pdf,
    upload_gdoc,
    upload_html,
) -> None:
    raw = imap.fetch_by_message_id(row.message_id)
    original = parse_rfc822(raw)
    reconstructed = reconstruct_message(
        original, gmail_msgid=row.gmail_msgid, settings=settings
    )
    when = _message_when(original)
    subject = str(reconstructed.message.get("Subject") or "")
    private = cfg.relay.private_address
    if row.kind == "html":
        if row.html_id:
            return
        body_part = reconstructed.message.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part is not None else ""
        html = archive_html_document(
            sender=reconstructed.sender_address,
            date_text=str(original.get("Date") or ""),
            subject=subject,
            body=body,
            private_address=private,
        )
        name = archive_html_name(when, subject, private_address=private)
        file_id = upload_html(access_token, cfg.archive.pdf_folder_id, name, html)
        ledger.record_html_id(row.gmail_msgid, file_id)
        return
    payloads = _pdf_payloads(reconstructed, when, subject, private)
    for name in row.expected_names:
        payload = payloads.get(name)
        if payload is None:
            continue
        if name not in row.pdf_ids:
            file_id = upload_pdf(access_token, cfg.archive.pdf_folder_id, name, payload)
            ledger.record_pdf_id(row.gmail_msgid, name, file_id)
            row.pdf_ids[name] = file_id
        if name not in row.doc_ids:
            doc_name = name[: -len(".pdf")] if name.lower().endswith(".pdf") else name
            file_id = upload_gdoc(access_token, cfg.archive.docs_folder_id, doc_name, payload)
            ledger.record_doc_id(row.gmail_msgid, name, file_id)
            row.doc_ids[name] = file_id


def _plan(
    cfg: AppConfig, original: EmailMessage, reconstructed: Reconstruction
) -> tuple[str, list[str]]:
    when = _message_when(original)
    subject = str(reconstructed.message.get("Subject") or "")
    names = list(_pdf_payloads(reconstructed, when, subject, cfg.relay.private_address))
    if names:
        return "pdfs", names
    return "html", []


def _pdf_payloads(
    reconstructed: Reconstruction,
    when: datetime,
    subject: str,
    private: str,
) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for item in reconstructed.attachments:
        if item.action != AttachmentDecision.ALLOW:
            continue
        if not item.safe_filename.lower().endswith(".pdf"):
            continue
        name = archive_pdf_name(
            when, subject, item.safe_filename, private_address=private
        )
        out[name] = item.payload
    return out


def _message_when(original: EmailMessage) -> datetime:
    raw = str(original.get("Date") or "")
    try:
        parsed = parsedate_to_datetime(raw) if raw else None
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        return datetime.now()
    return parsed


def _maybe_write_intake_handoff(
    cfg: AppConfig,
    ledger: Ledger,
    *,
    row: ArchiveRow,
    imap: object,
    settings: ReconstructionSettings,
) -> None:
    if row.intake_written_at:
        return
    raw = imap.fetch_by_message_id(row.message_id)
    original = parse_rfc822(raw)
    reconstructed = reconstruct_message(
        original, gmail_msgid=row.gmail_msgid, settings=settings
    )
    when = _message_when(original)
    subject = str(reconstructed.message.get("Subject") or "")
    private = cfg.relay.private_address
    original_date = str(original.get("Date") or "").strip() or None
    bundle_id = bundle_id_for_relay_key(row.gmail_msgid)
    if row.kind == "html":
        body_part = reconstructed.message.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part is not None else ""
        html = archive_html_document(
            sender=reconstructed.sender_address,
            date_text=str(original.get("Date") or ""),
            subject=subject,
            body=body if isinstance(body, str) else str(body),
            private_address=private,
        )
        html_name = archive_html_name(when, subject, private_address=private)
        file_payloads = {html_name: (html.encode("utf-8"), "text/html")}
        archive_kind = "html"
    else:
        pdf_payloads = _pdf_payloads(reconstructed, when, subject, private)
        if not pdf_payloads:
            return
        file_payloads = {
            name: (payload, "application/pdf") for name, payload in pdf_payloads.items()
        }
        archive_kind = "pdfs"
    maybe_write_intake_handoff(
        cfg.intake.handoff_dir,
        ledger,
        relay_key=row.gmail_msgid,
        reconstructed=reconstructed,
        original_date=original_date,
        row=row,
        file_payloads=file_payloads,
        bundle_id=bundle_id,
        archive_kind=archive_kind,
    )


def _missing(row: ArchiveRow) -> str:
    if row.kind == "html":
        return "html" if not row.html_id else ""
    missing: list[str] = []
    for name in row.expected_names:
        if not row.pdf_ids.get(name):
            missing.append(f"pdf:{name}")
        if not row.doc_ids.get(name):
            missing.append(f"doc:{name}")
    return ",".join(missing)
