from __future__ import annotations

import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

from research_relay.config import ProtonConfig
from research_relay.exceptions import ConfigError, PermanentRelayError, TemporaryRelayError


class ProtonSmtp:
    def __init__(self, cfg: ProtonConfig, password: str) -> None:
        self._cfg = cfg
        self._password = password
        self._from_address = cfg.from_address
        self._smtp: smtplib.SMTP | None = None

    def connect(self) -> None:
        context = build_ssl_context(self._cfg)
        try:
            if self._cfg.mode == "tls":
                smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                    self._cfg.smtp_host,
                    self._cfg.smtp_port,
                    timeout=self._cfg.timeout_seconds,
                    context=context,
                )
            else:
                smtp = smtplib.SMTP(
                    self._cfg.smtp_host,
                    self._cfg.smtp_port,
                    timeout=self._cfg.timeout_seconds,
                )
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(self._cfg.username, self._password)
            self._smtp = smtp
        except smtplib.SMTPResponseException as exc:
            _raise_smtp(exc)
        except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
            hint = ""
            if self._cfg.mode == "starttls" and exc.__class__.__name__ == "SMTPServerDisconnected":
                hint = '; Bridge 3 SMTP is often implicit TLS — set proton.mode = "tls"'
            raise TemporaryRelayError(f"SMTP connect failed: {exc.__class__.__name__}{hint}") from exc

    def send(self, message: EmailMessage, envelope_recipients: list[str]) -> None:
        smtp = self._smtp
        if smtp is None:
            raise TemporaryRelayError("SMTP client is not connected")
        payload = message.as_bytes()
        try:
            smtp.sendmail(self._from_address, list(envelope_recipients), payload)
        except smtplib.SMTPResponseException as exc:
            _raise_smtp(exc)
        except (OSError, smtplib.SMTPException) as exc:
            raise TemporaryRelayError(f"SMTP send failed: {exc.__class__.__name__}") from exc

    def noop(self) -> None:
        smtp = self._smtp
        if smtp is None:
            raise TemporaryRelayError("SMTP client is not connected")
        smtp.noop()

    def close(self) -> None:
        if self._smtp is None:
            return
        try:
            self._smtp.quit()
        except Exception:
            pass
        self._smtp = None


def build_ssl_context(cfg: ProtonConfig) -> ssl.SSLContext:
    if cfg.allow_insecure_tls:
        warning = (
            "WARNING: TLS certificate verification is disabled for Proton Bridge SMTP. "
            "This mode is for localhost troubleshooting only."
        )
        print(warning, file=sys.stderr)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ctx = ssl.create_default_context()
    ca_file = (cfg.ca_file or "").strip()
    if ca_file:
        path = Path(ca_file).expanduser()
        if not path.is_file():
            raise ConfigError(f"Proton Bridge certificate file not found: {path}")
        ctx.load_verify_locations(cafile=str(path))
        # Bridge certs are pinned via the exported CA; the CN may not match 127.0.0.1.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _raise_smtp(exc: smtplib.SMTPResponseException) -> None:
    code = getattr(exc, "smtp_code", 0) or 0
    detail = getattr(exc, "smtp_error", b"") or b""
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    detail = " ".join(str(detail).split())[:200]
    suffix = f": {detail}" if detail else ""
    if 400 <= code < 500:
        raise TemporaryRelayError(f"SMTP temporary error {code}{suffix}") from exc
    if 500 <= code < 600:
        raise PermanentRelayError(f"SMTP permanent error {code}{suffix}") from exc
    raise TemporaryRelayError(f"SMTP error {code}{suffix}") from exc
