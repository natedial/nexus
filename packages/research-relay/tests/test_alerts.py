from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import pytest

from research_relay.config import load_config
from research_relay.exceptions import ConfigError, KeychainError, TemporaryRelayError
from research_relay.ledger import Ledger
from research_relay.runner import RunResult


MINIMAL = """
[gmail]
username = "private.user@gmail.com"
imap_host = "imap.gmail.com"
imap_port = 993
all_mail_folder = "[Gmail]/All Mail"
search_query = "label:relay/pending -label:relay/sent -in:spam -in:trash"
label_pending = "Relay/pending"
label_sent = "Relay/sent"
label_error = "Relay/error"
timeout_seconds = 30
keychain_service = "research-relay-gmail"

[auth]
method = "app_password"

[proton]
smtp_host = "127.0.0.1"
smtp_port = 1025
mode = "starttls"
username = "relay@proton.me"
from_address = "relay@proton.me"
reply_to = "relay-reply@proton.me"
timeout_seconds = 30
keychain_service = "research-relay-proton-smtp"
ca_file = ""
allow_insecure_tls = false

[relay]
live_delivery = false
allow_subdomains = false
allowed_domains = ["candidates.edu"]
colleagues = ["c1@proton.me", "colleague2@example.org"]
private_address = "private.user@gmail.com"
message_id_domain = "relay.local"
hmac_keychain_service = "research-relay-hmac-key"
max_messages_per_run = 20

[attachments]
max_individual_bytes = 10485760
max_combined_bytes = 26214400
blocked_extensions = [".exe"]
allowed_extensions = []
on_prohibited = "skip"
quarantine_dir = "/tmp/relay-quarantine"

[retry]
max_attempts = 3
initial_backoff_seconds = 2
max_backoff_seconds = 30
permanent_failure_threshold = 5

[paths]
ledger = "/tmp/relay.sqlite"
lock_file = "/tmp/relay.lock"
log_file = "/tmp/relay.log"

[logging]
level = "INFO"
max_bytes = 1048576
backup_count = 5
"""


def _cfg(tmp_path: Path, extra: str = "") -> object:
    path = tmp_path / "config.toml"
    text = MINIMAL.replace('ledger = "/tmp/relay.sqlite"', f'ledger = "{tmp_path / "ledger.sqlite"}"')
    text = text.replace('lock_file = "/tmp/relay.lock"', f'lock_file = "{tmp_path / "relay.lock"}"')
    text = text.replace('log_file = "/tmp/relay.log"', f'log_file = "{tmp_path / "relay.log"}"')
    if extra:
        text += "\n" + extra
    path.write_text(text, encoding="utf-8")
    return load_config(path)


class RecordingSmtp:
    def __init__(self, fail_connect: bool = False) -> None:
        self.sent: list[tuple[EmailMessage, list[str]]] = []
        self.connects = 0
        self.closed = False
        self.fail_connect = fail_connect

    def connect(self) -> None:
        self.connects += 1
        if self.fail_connect:
            raise TemporaryRelayError("SMTP connect failed: ConnectionRefusedError")

    def send(self, message: EmailMessage, envelope_recipients: list[str]) -> None:
        self.sent.append((message, list(envelope_recipients)))

    def close(self) -> None:
        self.closed = True


def test_config_omitted_alerts_section_defaults_disabled(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert cfg.alerts.enabled is False
    assert cfg.alerts.channel == "email"
    assert cfg.alerts.to == ""
    assert cfg.alerts.imessage_to == ""
    assert cfg.alerts.cooldown_seconds == 21600
    assert cfg.alerts.dry_run is False


def test_config_loads_alerts_section(tmp_path: Path) -> None:
    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
channel = "both"
to = "ops@proton.me"
imessage_to = "+15555550100"
cooldown_seconds = 3600
dry_run = true
""",
    )
    assert cfg.alerts.enabled is True
    assert cfg.alerts.channel == "both"
    assert cfg.alerts.to == "ops@proton.me"
    assert cfg.alerts.imessage_to == "+15555550100"
    assert cfg.alerts.cooldown_seconds == 3600
    assert cfg.alerts.dry_run is True


def test_rejects_unknown_alert_channel(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="alerts.channel"):
        _cfg(
            tmp_path,
            """
[alerts]
channel = "twilio"
""",
        )


def test_classify_oauth_http_error() -> None:
    from research_relay.alerts import classify_exception

    event = classify_exception(TemporaryRelayError("Google OAuth token endpoint HTTP 400"))
    assert event.kind == "oauth"
    assert "400" in event.detail
    assert event.recovered is False


def test_classify_drive_auth_error() -> None:
    from research_relay.alerts import classify_exception
    from research_relay.exceptions import DriveAuthError

    event = classify_exception(DriveAuthError("Drive HTTP 401"))
    assert event.kind == "drive"


def test_classify_smtp_connect() -> None:
    from research_relay.alerts import classify_exception

    event = classify_exception(TemporaryRelayError("SMTP connect failed: ConnectionRefusedError"))
    assert event.kind == "smtp_connect"


def test_classify_imap_timeout() -> None:
    from research_relay.alerts import classify_exception

    event = classify_exception(TemporaryRelayError("IMAP timed out: TimeoutError"))
    assert event.kind == "imap_timeout"


def test_classify_max_runtime_system_exit() -> None:
    from research_relay.alerts import classify_exception

    event = classify_exception(SystemExit(1))
    assert event.kind == "max_runtime"


def test_classify_circuit_from_run_result() -> None:
    from research_relay.alerts import classify_run_result

    tripped = classify_run_result(RunResult(circuit_tripped=True))
    assert tripped.kind == "circuit"
    opened = classify_run_result(RunResult(circuit_open=True))
    assert opened.kind == "circuit"
    ok = classify_run_result(RunResult())
    assert ok.kind == "ok"
    assert ok.recovered is False


def test_classify_temp_failures_as_run_failed() -> None:
    from research_relay.alerts import classify_run_result

    event = classify_run_result(RunResult(temporary_failures=2, operational_failures=1))
    assert event.kind == "run_failed"
    assert "temp=2" in event.detail
    assert "ops=1" in event.detail


def test_first_success_does_not_notify(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, should_notify

    ledger = Ledger(tmp_path / "ledger.sqlite")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert should_notify(ledger, AlertEvent("ok", "run succeeded"), cooldown_seconds=21600, now=now) is False


def test_new_failure_notifies(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, record_notification, should_notify

    ledger = Ledger(tmp_path / "ledger.sqlite")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    event = AlertEvent("oauth", "Google OAuth token endpoint HTTP 400")
    assert should_notify(ledger, event, cooldown_seconds=21600, now=now) is True
    record_notification(ledger, event, now=now)
    later = now + timedelta(minutes=5)
    assert should_notify(ledger, event, cooldown_seconds=21600, now=later) is False


def test_same_failure_after_cooldown_notifies_again(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, record_notification, should_notify

    ledger = Ledger(tmp_path / "ledger.sqlite")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    event = AlertEvent("oauth", "Google OAuth token endpoint HTTP 400")
    record_notification(ledger, event, now=now)
    after = now + timedelta(seconds=21600)
    assert should_notify(ledger, event, cooldown_seconds=21600, now=after) is True


def test_new_failure_kind_notifies_immediately(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, record_notification, should_notify

    ledger = Ledger(tmp_path / "ledger.sqlite")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    record_notification(ledger, AlertEvent("oauth", "HTTP 400"), now=now)
    smtp = AlertEvent("smtp_connect", "SMTP connect failed")
    soon = now + timedelta(minutes=5)
    assert should_notify(ledger, smtp, cooldown_seconds=21600, now=soon) is True


def test_recovery_notifies_once(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, record_notification, should_notify

    ledger = Ledger(tmp_path / "ledger.sqlite")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    record_notification(ledger, AlertEvent("oauth", "HTTP 400"), now=now)
    recovered = AlertEvent("ok", "run succeeded", recovered=True)
    soon = now + timedelta(minutes=5)
    assert should_notify(ledger, recovered, cooldown_seconds=21600, now=soon) is True
    record_notification(ledger, recovered, now=soon)
    later = soon + timedelta(minutes=5)
    assert should_notify(ledger, AlertEvent("ok", "run succeeded"), cooldown_seconds=21600, now=later) is False


def test_alert_message_goes_only_to_ops_address_not_colleagues(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, build_alert_message

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
to = "ops@proton.me"
""",
    )
    event = AlertEvent("oauth", "Google OAuth token endpoint HTTP 400")
    message, envelope = build_alert_message(cfg, event)
    assert envelope == ["ops@proton.me"]
    assert message["To"] == "ops@proton.me"
    raw = message.as_bytes().decode("utf-8", errors="replace")
    assert "c1@proton.me" not in raw
    assert "colleague2@example.org" not in raw
    assert message["Auto-Submitted"] == "auto-generated"
    assert "FAIL" in (message["Subject"] or "")
    assert "oauth" in (message["Subject"] or "")


def test_alert_text_redacts_secrets_and_omits_bodies() -> None:
    from research_relay.alerts import AlertEvent, sanitize_alert_text

    secrets = ["super-secret-password", "private.user@gmail.com"]
    dirty = "login failed for private.user@gmail.com with super-secret-password; body: " + ("W" * 5000)
    out = sanitize_alert_text(dirty, secrets)
    assert "super-secret-password" not in out
    assert "private.user@gmail.com" not in out
    assert "[redacted]" in out
    assert "W" * 200 not in out
    assert len(out) < 500
    event = AlertEvent("run_failed", out)
    assert "W" * 200 not in event.detail


def test_notify_sends_email_and_skips_repeat_within_cooldown(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, notify

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
channel = "email"
to = "ops@proton.me"
cooldown_seconds = 21600
""",
    )
    smtp = RecordingSmtp()
    event = AlertEvent("oauth", "Google OAuth token endpoint HTTP 400")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp, now=now) is True
    assert len(smtp.sent) == 1
    assert smtp.closed is True
    soon = now + timedelta(minutes=5)
    smtp2 = RecordingSmtp()
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp2, now=soon) is False
    assert smtp2.sent == []


def test_notify_dry_run_does_not_send(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, notify

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
to = "ops@proton.me"
dry_run = true
""",
    )
    smtp = RecordingSmtp()
    event = AlertEvent("smtp_connect", "SMTP connect failed")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp, now=now) is True
    assert smtp.sent == []
    assert smtp.connects == 0


def test_notify_disabled_or_missing_recipient_is_silent(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, notify

    cfg = _cfg(tmp_path)
    smtp = RecordingSmtp()
    event = AlertEvent("oauth", "HTTP 400")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp, now=now) is False
    assert smtp.sent == []


def test_notify_falls_back_to_imessage_when_smtp_fails(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, notify

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
channel = "email"
to = "ops@proton.me"
imessage_to = "+15555550100"
""",
    )
    smtp = RecordingSmtp(fail_connect=True)
    sent: list[tuple[str, str]] = []

    def fake_imessage(to: str, body: str) -> None:
        sent.append((to, body))

    event = AlertEvent("smtp_connect", "SMTP connect failed: ConnectionRefusedError")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert (
        notify(
            cfg,
            event,
            proton_password="pw",
            smtp_client=smtp,
            imessage_send=fake_imessage,
            now=now,
        )
        is True
    )
    assert smtp.sent == []
    assert sent and sent[0][0] == "+15555550100"
    assert "smtp_connect" in sent[0][1]
    assert "pw" not in sent[0][1]


def test_notify_force_bypasses_cooldown(tmp_path: Path) -> None:
    from research_relay.alerts import AlertEvent, notify

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
to = "ops@proton.me"
""",
    )
    event = AlertEvent("test", "manual test")
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    smtp = RecordingSmtp()
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp, now=now, force=True) is True
    smtp2 = RecordingSmtp()
    assert notify(cfg, event, proton_password="pw", smtp_client=smtp2, now=now, force=True) is True
    assert len(smtp2.sent) == 1


def test_cli_parses_alert_test() -> None:
    from research_relay.cli import parse_cli

    args = parse_cli(["alert-test", "--config", "/tmp/relay.toml"])
    assert args.command == "alert-test"
    assert args.config == "/tmp/relay.toml"


def test_classify_keychain_and_config() -> None:
    from research_relay.alerts import classify_exception

    assert classify_exception(KeychainError("missing item")).kind == "config"
    assert classify_exception(ConfigError("bad toml")).kind == "config"


def test_health_reports_alerts_disabled(tmp_path: Path) -> None:
    from research_relay.health import run_health

    cfg = _cfg(tmp_path)
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    check = next(item for item in report.checks if item.name == "alerts")
    assert check.ok is True
    assert "disabled" in check.detail


def test_health_fails_when_alerts_enabled_without_recipient(tmp_path: Path) -> None:
    from research_relay.health import run_health

    cfg = _cfg(
        tmp_path,
        """
[alerts]
enabled = true
""",
    )
    report = run_health(cfg, connect_network=False, gmail_password="x", proton_password="y", hmac_key="z")
    check = next(item for item in report.checks if item.name == "alerts")
    assert check.ok is False
