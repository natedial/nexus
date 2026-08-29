from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
import sqlite3

from research_relay.auth import build_auth
from research_relay.config import AppConfig
from research_relay.ledger import Ledger
from research_relay.gmail_imap import GmailImap
from research_relay.keychain import get_generic_password, keychain_item_exists
from research_relay.proton_imap import ProtonImap
from research_relay.proton_smtp import ProtonSmtp, build_ssl_context


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class HealthReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))


def run_health(
    cfg: AppConfig,
    *,
    connect_network: bool = True,
    gmail_password: str | None = None,
    proton_password: str | None = None,
    hmac_key: str | None = None,
) -> HealthReport:
    report = HealthReport()
    report.add("config", True, f"loaded {cfg.source_path}")

    gmail_ok = keychain_item_exists(cfg.gmail.keychain_service, cfg.gmail.username)
    proton_ok = keychain_item_exists(cfg.proton.keychain_service, cfg.proton.username)
    hmac_ok = keychain_item_exists(cfg.relay.hmac_keychain_service, "hmac")
    if gmail_password is not None:
        gmail_ok = bool(gmail_password)
    if proton_password is not None:
        proton_ok = bool(proton_password)
    if hmac_key is not None:
        hmac_ok = bool(hmac_key)

    if cfg.auth.method == "oauth2":
        creds = cfg.auth.credentials_file
        token = cfg.auth.token_file
        report.add("oauth.credentials", bool(creds and Path(creds).is_file()), str(creds))
        report.add("oauth.token", bool(token and Path(token).is_file()), str(token))
    else:
        report.add("keychain.gmail", gmail_ok, cfg.gmail.keychain_service)
    report.add("keychain.proton", proton_ok, cfg.proton.keychain_service)
    report.add("keychain.hmac", hmac_ok, cfg.relay.hmac_keychain_service)

    try:
        cfg.paths.ledger.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(cfg.paths.ledger)
        conn.execute("CREATE TABLE IF NOT EXISTS health_probe (id INTEGER)")
        conn.execute("INSERT INTO health_probe (id) VALUES (1)")
        conn.execute("DELETE FROM health_probe")
        conn.commit()
        conn.close()
        report.add("sqlite", True, str(cfg.paths.ledger))
    except Exception as exc:
        report.add("sqlite", False, exc.__class__.__name__)

    try:
        ledger = Ledger(cfg.paths.ledger)
        if ledger.circuit_is_open():
            report.add("circuit", False, ledger.circuit_reason() or "open")
        else:
            report.add("circuit", True, "closed")
        ledger.close()
    except Exception as exc:
        report.add("circuit", False, exc.__class__.__name__)

    alerts = cfg.alerts
    if not alerts.enabled:
        report.add("alerts", True, "disabled")
    elif not alerts.to and not alerts.imessage_to:
        report.add("alerts", False, "enabled but no alerts.to or alerts.imessage_to")
    elif alerts.channel == "imessage" and not alerts.imessage_to:
        report.add("alerts", False, "channel=imessage but alerts.imessage_to is empty")
    else:
        dest = "email" if alerts.to else "imessage"
        extra = " dry-run" if alerts.dry_run else ""
        report.add(
            "alerts",
            True,
            f"channel={alerts.channel} via {dest} cooldown={alerts.cooldown_seconds}s{extra}",
        )

    try:
        build_ssl_context(cfg.proton)
        report.add(
            "tls",
            True,
            "insecure localhost TLS" if cfg.proton.allow_insecure_tls else "certificate verification enabled",
        )
    except Exception as exc:
        report.add("tls", False, str(exc))

    if not connect_network:
        _archive_health(cfg, report, connect_network=False)
        return report

    try:
        if cfg.auth.method == "oauth2":
            auth = build_auth(
                "oauth2",
                username=cfg.gmail.username,
                credentials_file=cfg.auth.credentials_file,
                token_file=cfg.auth.token_file,
                access_token=gmail_password,
            )
        else:
            password = gmail_password
            if password is None:
                password = get_generic_password(cfg.gmail.keychain_service, cfg.gmail.username)
            auth = build_auth(cfg.auth.method, username=cfg.gmail.username, password=password)
        client = GmailImap(cfg, auth)
        client.connect()
        names = client.list_mailbox_names()
        joined = "\n".join(names).lower()
        wanted = (
            cfg.gmail.label_pending,
            cfg.gmail.label_sent,
            cfg.gmail.label_error,
        )
        missing = [label for label in wanted if label.lower() not in joined]
        client.noop()
        client.close()
        report.add("gmail.imap", True, cfg.gmail.all_mail_folder)
        if missing:
            report.add(
                "gmail.labels",
                True,
                "IMAP connected; labels "
                + ", ".join(missing)
                + " were not listed yet (Gmail user labels may appear after first use)",
            )
        else:
            report.add("gmail.labels", True, ", ".join(wanted))
    except Exception as exc:
        report.add("gmail.imap", False, _health_error(exc))

    try:
        password = proton_password
        if password is None:
            import os

            password = os.environ.get("RESEARCH_RELAY_PROTON_PASSWORD", "").strip() or None
        if password is None:
            password = get_generic_password(cfg.proton.keychain_service, cfg.proton.username)
        smtp = ProtonSmtp(cfg.proton, password)
        smtp.connect()
        smtp.noop()
        smtp.close()
        report.add("proton.smtp", True, f"{cfg.proton.smtp_host}:{cfg.proton.smtp_port}")
    except Exception as exc:
        report.add("proton.smtp", False, _health_error(exc))
        _archive_health(cfg, report, connect_network=True)
        return report

    try:
        client = ProtonImap(cfg, password)
        client.connect()
        names = client.list_mailbox_names()
        joined = "\n".join(names).lower().replace("\\", "")
        wanted = (
            cfg.proton.folder_pending,
            cfg.proton.folder_sent,
            cfg.proton.folder_error,
        )
        missing = [folder for folder in wanted if folder.replace("\\", "").lower() not in joined]
        client.noop()
        client.close()
        report.add("proton.imap", True, f"{cfg.proton.imap_host}:{cfg.proton.imap_port}")
        if missing:
            report.add(
                "proton.labels",
                True,
                "IMAP connected; folders "
                + ", ".join(missing)
                + " were not listed yet (create Relay/pending, Relay/sent, Relay/error as Proton labels)",
            )
        else:
            report.add("proton.labels", True, ", ".join(wanted))
    except Exception as exc:
        report.add("proton.imap", False, _health_error(exc))

    _archive_health(cfg, report, connect_network=connect_network)
    return report


def _archive_health(cfg: AppConfig, report: HealthReport, *, connect_network: bool) -> None:
    archive = cfg.archive
    if not archive.enabled:
        report.add("archive", True, "disabled")
        return
    report.add("archive", True, "enabled")
    try:
        ledger = Ledger(cfg.paths.ledger)
        unrecoverable = ledger.count_unrecoverable()
        stale = ledger.stale_incomplete(max_age=timedelta(hours=9))
        ledger.close()
    except Exception as exc:
        report.add("archive.ledger", False, exc.__class__.__name__)
        return
    report.add("archive.unrecoverable", unrecoverable == 0, f"count={unrecoverable}")
    report.add(
        "archive.stale",
        len(stale) == 0,
        f"incomplete_older_than_9h={len(stale)}",
    )
    if not connect_network:
        return
    if cfg.auth.method != "oauth2" or not cfg.auth.credentials_file or not cfg.auth.token_file:
        report.add("archive.drive", False, "oauth2 token required")
        return
    try:
        from research_relay.drive_archive import get_file_metadata
        from research_relay.oauth import OAuthTokenStore

        token = OAuthTokenStore(cfg.auth.credentials_file, cfg.auth.token_file).get_access_token()
        for name, folder_id in (("pdfs", archive.pdf_folder_id), ("docs", archive.docs_folder_id)):
            meta = get_file_metadata(access_token=token, file_id=folder_id)
            mime = str(meta.get("mimeType") or "")
            ok = mime == "application/vnd.google-apps.folder"
            report.add(f"archive.folder.{name}", ok, mime or folder_id)
    except Exception as exc:
        report.add("archive.drive", False, _health_error(exc))


def _health_error(exc: BaseException) -> str:
    text = str(exc).strip()
    cause = exc.__cause__
    if cause is not None:
        extra = cause.__class__.__name__
        if text:
            return f"{exc.__class__.__name__}: {text} ({extra})"
        return f"{exc.__class__.__name__} ({extra})"
    if text and text != exc.__class__.__name__:
        return f"{exc.__class__.__name__}: {text}"
    return exc.__class__.__name__
