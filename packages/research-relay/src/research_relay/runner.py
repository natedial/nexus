from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path

from research_relay.archive_job import enqueue_proton_archive
from research_relay.attachments import AttachmentDecision, AttachmentPolicy
from research_relay.config import AppConfig
from research_relay.domain import address_is_one_of, domain_allowed, extract_sender_mailbox, message_id_from_domain
from research_relay.exceptions import PermanentRelayError, TemporaryRelayError
from research_relay.ledger import (
    STATUS_PERMANENT_ERROR,
    STATUS_SMTP_ACCEPTED,
    Ledger,
)
from research_relay.reconstruct import ReconstructionSettings, reconstruct_message
from research_relay.redact import redact_text
from research_relay.stamp import message_is_own_output

log = logging.getLogger("research_relay")


@dataclass
class RunResult:
    dry_run: bool = False
    sent: int = 0
    label_retries: int = 0
    temporary_failures: int = 0
    permanent_failures: int = 0
    operational_failures: int = 0
    skipped: int = 0
    dry_run_candidates: int = 0
    circuit_open: bool = False
    circuit_tripped: bool = False
    daily_cap_reached: bool = False
    notes: list[str] = field(default_factory=list)

    def exit_code(self) -> int:
        if self.operational_failures or self.temporary_failures or self.circuit_open or self.circuit_tripped:
            return 1
        return 0


def process_messages(
    cfg: AppConfig,
    *,
    imap: object,
    smtp: object,
    hmac_key: bytes,
    dry_run: bool,
    sleeper=time.sleep,
    extra_imaps: list | None = None,
) -> RunResult:
    result = RunResult(dry_run=dry_run)
    ledger = Ledger(cfg.paths.ledger)
    settings = _settings(cfg, hmac_key)
    sources = [imap, *(extra_imaps or [])]
    try:
        if ledger.circuit_is_open():
            result.circuit_open = True
            log.error("circuit breaker open reason=%s", ledger.circuit_reason() or "open")
        used = 0
        n_sources = max(1, len(sources))
        for index, source in enumerate(sources):
            remaining = cfg.relay.max_messages_per_run - used
            remaining_sources = n_sources - index
            if remaining <= 0:
                break
            budget = remaining // remaining_sources
            if budget <= 0:
                continue
            counter = getattr(source, "count_pending", None)
            pending_before = int(counter()) if callable(counter) else None
            sent_before = result.sent
            log.info("searching %s budget=%s", source.__class__.__name__, budget)
            pending = list(source.search_pending(limit=budget))
            pending = pending[:remaining]
            for msgid in pending:
                _process_one(
                    cfg,
                    imap=source,
                    smtp=smtp,
                    ledger=ledger,
                    settings=settings,
                    gmail_msgid=str(msgid),
                    dry_run=dry_run,
                    result=result,
                    sleeper=sleeper,
                    hmac_key=hmac_key,
                )
                used += 1
            dismiss = getattr(source, "dismiss_gmail_copies", None)
            if callable(dismiss):
                result.skipped += int(dismiss(dry_run=dry_run))
            if (
                not dry_run
                and pending_before is not None
                and result.sent > sent_before
                and callable(counter)
            ):
                pending_after = int(counter())
                if pending_after >= pending_before:
                    reason = (
                        f"proton pending did not shrink before={pending_before} after={pending_after} "
                        f"sent={result.sent - sent_before}"
                    )
                    ledger.trip_circuit(reason)
                    result.circuit_tripped = True
                    log.error("circuit breaker tripped %s", reason)
    finally:
        ledger.close()
    return result


def _process_one(
    cfg: AppConfig,
    *,
    imap: object,
    smtp: object,
    ledger: Ledger,
    settings: ReconstructionSettings,
    gmail_msgid: str,
    dry_run: bool,
    result: RunResult,
    sleeper,
    hmac_key: bytes,
) -> None:
    row = ledger.get(gmail_msgid)
    if row and row.status == "labels_updated":
        result.skipped += 1
        return
    if row and row.status == STATUS_SMTP_ACCEPTED:
        if dry_run:
            result.dry_run_candidates += 1
            log.info("dry-run would retry Gmail labels for msgid hash %s", _short(gmail_msgid))
            return
        try:
            imap.apply_sent(gmail_msgid)
            ledger.record_labels_updated(gmail_msgid)
            result.label_retries += 1
            log.info("retried Gmail labels after prior SMTP success msgid=%s", _short(gmail_msgid))
        except Exception as exc:
            result.operational_failures += 1
            log.warning("label retry failed msgid=%s error=%s", _short(gmail_msgid), exc.__class__.__name__)
        return
    if row and row.status == STATUS_PERMANENT_ERROR:
        if dry_run:
            result.skipped += 1
            return
        try:
            imap.apply_error(gmail_msgid)
            ledger.record_labels_updated(gmail_msgid)
            result.label_retries += 1
        except Exception:
            result.operational_failures += 1
        return
    if row and not ledger.ready_for_retry(gmail_msgid):
        result.skipped += 1
        return

    try:
        raw = imap.fetch_message(gmail_msgid)
        original = BytesParser(policy=policy.default).parsebytes(raw)
        from_header = str(original.get("From") or "")
        if _is_own_relay_message(cfg, original, hmac_key):
            result.skipped += 1
            log.info("skipping own relay output msgid=%s", _short(gmail_msgid))
            if dry_run:
                return
            try:
                imap.apply_sent(gmail_msgid)
                ledger.record_labels_updated(gmail_msgid)
            except Exception:
                result.operational_failures += 1
            return
        if not domain_allowed(from_header, cfg.relay.allowed_domains, cfg.relay.allow_subdomains):
            try:
                domain = extract_sender_mailbox(from_header).domain
            except ValueError:
                domain = "invalid"
            raise PermanentRelayError(f"sender domain {domain} is not on the allowlist")
        reconstructed = reconstruct_message(original, gmail_msgid=gmail_msgid, settings=settings)
    except PermanentRelayError as exc:
        _handle_permanent(cfg, imap, ledger, gmail_msgid, str(exc), dry_run, result)
        return
    except TemporaryRelayError as exc:
        _handle_temp(cfg, ledger, gmail_msgid, str(exc), dry_run, result)
        return
    except Exception as exc:
        log.warning("message parse failed msgid=%s error=%s", _short(gmail_msgid), exc.__class__.__name__)
        _handle_temp(cfg, ledger, gmail_msgid, exc.__class__.__name__, dry_run, result)
        return

    summary = _dry_summary(cfg, gmail_msgid, reconstructed.message, reconstructed.notes)
    if dry_run:
        result.dry_run_candidates += 1
        log.info("dry-run %s", summary)
        print(summary)
        return

    if str(gmail_msgid).startswith("proton:") and cfg.archive.enabled:
        try:
            enqueue_proton_archive(
                cfg, ledger, str(gmail_msgid), original=original, reconstructed=reconstructed
            )
        except Exception as exc:
            log.warning(
                "archive enqueue failed msgid=%s error=%s",
                _short(gmail_msgid),
                exc.__class__.__name__,
            )

    _quarantine(cfg, gmail_msgid, reconstructed.attachments)

    if result.circuit_open or result.circuit_tripped:
        result.skipped += 1
        log.info("skipping send; circuit breaker open msgid=%s", _short(gmail_msgid))
        return
    if ledger.sent_today() >= cfg.relay.max_messages_per_day:
        result.daily_cap_reached = True
        result.skipped += 1
        log.warning(
            "daily send cap reached sent_today=%s cap=%s msgid=%s",
            ledger.sent_today(),
            cfg.relay.max_messages_per_day,
            _short(gmail_msgid),
        )
        return

    sent = False
    last_error = "smtp send failed"
    attempts = max(1, cfg.retry.max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            smtp.send(reconstructed.message, envelope_recipients=list(cfg.relay.colleagues))
            sent = True
            break
        except PermanentRelayError as exc:
            _handle_permanent(cfg, imap, ledger, gmail_msgid, str(exc), dry_run, result)
            return
        except (TemporaryRelayError, ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc.__class__.__name__
            if attempt < attempts:
                delay = min(
                    cfg.retry.max_backoff_seconds,
                    cfg.retry.initial_backoff_seconds * (2 ** (attempt - 1)),
                )
                sleeper(delay)
        except Exception as exc:
            last_error = exc.__class__.__name__
            break

    if not sent:
        _handle_temp(cfg, ledger, gmail_msgid, last_error, dry_run, result)
        return

    # Small duplicate-delivery window: SMTP has accepted the message, but the
    # local success record has not been committed yet. If the process dies here,
    # the next run may send a second copy.
    ledger.record_smtp_accepted(gmail_msgid)
    ledger.record_send()
    result.sent += 1
    try:
        imap.apply_sent(gmail_msgid)
        ledger.record_labels_updated(gmail_msgid)
        log.info("delivered msgid=%s", _short(gmail_msgid))
    except Exception as exc:
        result.operational_failures += 1
        log.warning(
            "SMTP accepted but label update failed msgid=%s error=%s",
            _short(gmail_msgid),
            exc.__class__.__name__,
        )


def _handle_temp(
    cfg: AppConfig,
    ledger: Ledger,
    gmail_msgid: str,
    error: str,
    dry_run: bool,
    result: RunResult,
) -> None:
    result.temporary_failures += 1
    log.info("temporary failure msgid=%s error=%s", _short(gmail_msgid), error)
    if dry_run:
        return
    row = ledger.get(gmail_msgid)
    count = (row.failure_count if row else 0) + 1
    backoff = min(
        cfg.retry.max_backoff_seconds,
        cfg.retry.initial_backoff_seconds * (2 ** max(0, count - 1)),
    )
    if count >= cfg.retry.permanent_failure_threshold:
        ledger.record_permanent_error(gmail_msgid, error)
        result.permanent_failures += 1
        result.temporary_failures -= 1
        log.warning("permanent failure threshold reached msgid=%s", _short(gmail_msgid))
        return
    ledger.record_temp_failure(gmail_msgid, error, backoff_seconds=int(backoff))


def _handle_permanent(
    cfg: AppConfig,
    imap: object,
    ledger: Ledger,
    gmail_msgid: str,
    error: str,
    dry_run: bool,
    result: RunResult,
) -> None:
    result.permanent_failures += 1
    if dry_run:
        log.warning("dry-run would reject msgid=%s error=%s", _short(gmail_msgid), error)
        return
    log.warning("permanent failure msgid=%s error=%s", _short(gmail_msgid), error)
    ledger.record_permanent_error(gmail_msgid, error)
    try:
        imap.apply_error(gmail_msgid)
        ledger.record_labels_updated(gmail_msgid)
    except Exception:
        result.operational_failures += 1


def _is_own_relay_message(cfg: AppConfig, original, hmac_key: bytes) -> bool:
    if address_is_one_of(
        str(original.get("From") or ""),
        [cfg.proton.from_address, cfg.proton.reply_to],
    ):
        return True
    if message_id_from_domain(str(original.get("Message-ID") or ""), cfg.relay.message_id_domain):
        return True
    return message_is_own_output(original, hmac_key)


def _settings(cfg: AppConfig, hmac_key: bytes) -> ReconstructionSettings:
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


def _quarantine(cfg: AppConfig, gmail_msgid: str, attachments) -> None:
    if cfg.attachments.on_prohibited != "quarantine":
        return
    directory = Path(cfg.attachments.quarantine_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    for item in attachments:
        if item.action != AttachmentDecision.QUARANTINE:
            continue
        target = directory / f"{_safe_id(gmail_msgid)}-{item.safe_filename}"
        target.write_bytes(item.payload or b"")


def _dry_summary(cfg: AppConfig, gmail_msgid: str, message, notes: list[str]) -> str:
    private = cfg.relay.private_address
    subject = redact_text(str(message.get("Subject") or ""), private)
    sender = redact_text(str(message.get_body(preferencelist=("plain",)).get_content().splitlines()[0]), private)
    filenames = []
    for part in message.iter_attachments():
        filenames.append(redact_text(part.get_filename() or "attachment", private))
    return (
        f"msgid={_short(gmail_msgid)} subject={subject!r} {sender} "
        f"attachments={filenames} notes={notes}"
    )


def _short(gmail_msgid: str) -> str:
    text = gmail_msgid.removeprefix("proton:")
    return text[-8:] if len(text) > 8 else text


def _safe_id(gmail_msgid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in gmail_msgid)[:80]
