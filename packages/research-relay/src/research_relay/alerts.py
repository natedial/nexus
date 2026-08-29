from __future__ import annotations

from dataclasses import dataclass
import logging
import subprocess
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Callable

from research_relay.config import AppConfig
from research_relay.exceptions import ConfigError, DriveAuthError, KeychainError, TemporaryRelayError
from research_relay.ledger import Ledger
from research_relay.logging_setup import redact_log_message
from research_relay.runner import RunResult

log = logging.getLogger("research_relay")

_MAX_ALERT = 240
_MAX_IMESSAGE = 200

ImessageSender = Callable[[str, str], None]


@dataclass(frozen=True)
class AlertEvent:
    kind: str
    detail: str
    recovered: bool = False


def classify_exception(exc: BaseException) -> AlertEvent:
    if isinstance(exc, SystemExit):
        return AlertEvent("max_runtime", "max runtime exceeded")
    if isinstance(exc, (ConfigError, KeychainError)):
        return AlertEvent("config", _clip(str(exc) or exc.__class__.__name__))
    if isinstance(exc, DriveAuthError):
        return AlertEvent("drive", _clip(str(exc) or exc.__class__.__name__))
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "oauth" in lowered or "token endpoint" in lowered:
        return AlertEvent("oauth", _clip(text))
    if "drive http" in lowered:
        return AlertEvent("drive", _clip(text))
    if "smtp connect" in lowered:
        return AlertEvent("smtp_connect", _clip(text))
    if "imap timed out" in lowered or "timed out" in lowered:
        return AlertEvent("imap_timeout", _clip(text))
    return AlertEvent("run_failed", _clip(text))


def classify_run_result(result: RunResult) -> AlertEvent:
    if result.circuit_tripped:
        return AlertEvent("circuit", "circuit breaker tripped")
    if result.circuit_open:
        return AlertEvent("circuit", "circuit breaker open")
    if result.temporary_failures or result.operational_failures:
        return AlertEvent(
            "run_failed",
            f"temp={result.temporary_failures} ops={result.operational_failures}",
        )
    return AlertEvent("ok", "run succeeded")


def sanitize_alert_text(text: str, secrets: list[str] | tuple[str, ...] | None) -> str:
    out = redact_log_message(text or "", secrets)
    out = " ".join(out.split())
    return _clip(out)


def should_notify(
    ledger: Ledger,
    event: AlertEvent,
    cooldown_seconds: int,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    last_status = ledger.alert_status()
    last_kind = ledger.alert_kind()
    last_sent = ledger.alert_sent_at()
    if event.kind == "ok":
        return last_status == "fail"
    if last_status != "fail" or last_kind != event.kind:
        return True
    if last_sent is None:
        return True
    elapsed = (current - last_sent).total_seconds()
    return elapsed >= max(0, int(cooldown_seconds))


def record_notification(ledger: Ledger, event: AlertEvent, now: datetime | None = None) -> None:
    current = now or datetime.now(timezone.utc)
    if event.kind == "ok":
        ledger.record_alert("ok", "", current)
    else:
        ledger.record_alert("fail", event.kind, current)


def build_alert_message(cfg: AppConfig, event: AlertEvent) -> tuple[EmailMessage, list[str]]:
    to_addr = cfg.alerts.to.strip()
    recovered = event.recovered or event.kind == "ok"
    if recovered:
        subject = "research-relay OK: recovered"
        status = "OK"
    else:
        subject = f"research-relay FAIL: {event.kind}"
        status = "FAIL"
    body = (
        "research-relay operational alert\n"
        f"status: {status}\n"
        f"kind: {event.kind}\n"
        f"detail: {event.detail}\n"
    )
    message = EmailMessage()
    message["From"] = cfg.proton.from_address
    message["To"] = to_addr
    message["Subject"] = subject
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(body)
    return message, [to_addr]


def notify(
    cfg: AppConfig,
    event: AlertEvent,
    *,
    proton_password: str | None,
    smtp_client: object | None = None,
    imessage_send: ImessageSender | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    if not cfg.alerts.enabled:
        return False
    if not cfg.alerts.to.strip() and not cfg.alerts.imessage_to.strip():
        return False

    current = now or datetime.now(timezone.utc)
    secrets = _secrets(cfg, proton_password)
    clean = AlertEvent(
        event.kind,
        sanitize_alert_text(event.detail, secrets),
        recovered=event.recovered,
    )
    ledger = Ledger(cfg.paths.ledger)
    try:
        last_kind = ledger.alert_kind()
        last_status = ledger.alert_status()
        if clean.kind == "ok" and last_status == "fail":
            clean = AlertEvent("ok", f"recovered from {last_kind or 'failure'}", recovered=True)
        if not force and not should_notify(ledger, clean, cfg.alerts.cooldown_seconds, now=current):
            return False
        delivered = False
        if cfg.alerts.dry_run:
            log.info("alert dry-run kind=%s recovered=%s", clean.kind, clean.recovered)
            delivered = True
        else:
            delivered = _deliver(
                cfg,
                clean,
                proton_password,
                smtp_client=smtp_client,
                imessage_send=imessage_send,
            )
        if delivered:
            record_notification(ledger, clean, now=current)
            log.info("alert sent kind=%s recovered=%s", clean.kind, clean.recovered)
        return delivered
    finally:
        ledger.close()


def maybe_alert(
    cfg: AppConfig,
    event: AlertEvent | None,
    proton_password: str | None,
    *,
    skip: bool = False,
) -> None:
    if skip or event is None:
        return
    try:
        notify(cfg, event, proton_password=proton_password)
    except Exception as exc:
        log.warning("alert send failed error=%s", exc.__class__.__name__)


def send_imessage(to: str, body: str) -> None:
    dest = (to or "").strip()
    text = (body or "").strip()
    if not dest or not text:
        raise TemporaryRelayError("iMessage destination or body is empty")
    script = (
        "on run argv\n"
        "set dest to item 1 of argv\n"
        "set msg to item 2 of argv\n"
        "tell application \"Messages\"\n"
        "set svc to 1st service whose service type is iMessage\n"
        "send msg to buddy dest of svc\n"
        "end tell\n"
        "end run\n"
    )
    completed = subprocess.run(
        ["osascript", "-", dest, text],
        input=script,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "osascript failed").strip().splitlines()
        brief = err[0] if err else "osascript failed"
        raise TemporaryRelayError(f"iMessage send failed: {brief[:120]}")


def _deliver(
    cfg: AppConfig,
    event: AlertEvent,
    proton_password: str | None,
    *,
    smtp_client: object | None,
    imessage_send: ImessageSender | None,
) -> bool:
    channel = cfg.alerts.channel
    email_to = cfg.alerts.to.strip()
    imessage_to = cfg.alerts.imessage_to.strip()
    want_email = channel in {"email", "both"} and bool(email_to)
    want_imessage = channel in {"imessage", "both"} and bool(imessage_to)
    email_ok = False
    if want_email:
        try:
            _send_email(cfg, event, proton_password, smtp_client)
            email_ok = True
        except Exception as exc:
            log.warning("alert email failed error=%s", exc.__class__.__name__)
    imessage_ok = False
    use_imessage = want_imessage or (not email_ok and bool(imessage_to))
    if use_imessage:
        try:
            sender = imessage_send or send_imessage
            sender(imessage_to, _imessage_body(event))
            imessage_ok = True
        except Exception as exc:
            log.warning("alert imessage failed error=%s", exc.__class__.__name__)
    return email_ok or imessage_ok


def _send_email(
    cfg: AppConfig,
    event: AlertEvent,
    proton_password: str | None,
    smtp_client: object | None,
) -> None:
    client = smtp_client
    if client is None:
        if not proton_password:
            raise TemporaryRelayError("alert email needs Proton SMTP password")
        from research_relay.proton_smtp import ProtonSmtp

        client = ProtonSmtp(cfg.proton, proton_password)
    try:
        connect = getattr(client, "connect", None)
        if callable(connect):
            connect()
        message, envelope = build_alert_message(cfg, event)
        client.send(message, envelope)
    finally:
        closer = getattr(client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


def _imessage_body(event: AlertEvent) -> str:
    status = "OK" if event.recovered or event.kind == "ok" else "FAIL"
    text = f"research-relay {status}: {event.kind} {event.detail}"
    return sanitize_alert_text(text, None)[:_MAX_IMESSAGE]


def _secrets(cfg: AppConfig, proton_password: str | None) -> list[str]:
    import os

    extras = [
        cfg.relay.private_address,
        cfg.gmail.username,
        cfg.proton.username,
        proton_password or "",
        os.environ.get("RESEARCH_RELAY_HMAC_KEY", "").strip(),
        os.environ.get("RESEARCH_RELAY_PROTON_PASSWORD", "").strip(),
    ]
    return [item for item in extras if item]


def _clip(text: str) -> str:
    out = (text or "").strip()
    if len(out) > _MAX_ALERT:
        return out[:_MAX_ALERT] + "…"
    return out
