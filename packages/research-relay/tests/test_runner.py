import logging
from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path

import pytest

from research_relay.config import load_config
from research_relay.exceptions import AlreadyRunningError
from research_relay.ledger import Ledger
from research_relay.lock import FileLock
from research_relay.logging_setup import install_logging, redact_log_message
from research_relay.runner import RunResult, process_messages
from research_relay.stamp import stamp_line


class FakeImap:
    def __init__(self, messages: dict[str, dict]):
        self.messages = messages
        self.labels: dict[str, set[str]] = {
            msgid: set(info.get("labels", {"Relay/pending"}))
            for msgid, info in messages.items()
        }
        self.selected = None
        self.fetches: list[str] = []

    def search_pending(self, limit: int | None = None) -> list[str]:
        pending = [
            msgid
            for msgid, info in self.messages.items()
            if "Relay/pending" in self.labels[msgid]
            and "Relay/sent" not in self.labels[msgid]
            and "Relay/error" not in self.labels[msgid]
        ]
        if limit is not None:
            return pending[: max(0, int(limit))]
        return pending

    def fetch_message(self, gmail_msgid: str) -> bytes:
        self.fetches.append(gmail_msgid)
        return self.messages[gmail_msgid]["raw"]

    def apply_sent(self, gmail_msgid: str) -> None:
        self.labels[gmail_msgid].add("Relay/sent")
        self.labels[gmail_msgid].discard("Relay/pending")

    def apply_error(self, gmail_msgid: str) -> None:
        self.labels[gmail_msgid].add("Relay/error")
        self.labels[gmail_msgid].discard("Relay/pending")


class FakeSmtp:
    def __init__(self, fail_times: int = 0):
        self.sent: list[tuple[str, list[str], bytes]] = []
        self.fail_times = fail_times
        self.attempts = 0

    def send(self, message: EmailMessage, envelope_recipients: list[str]) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise ConnectionError("smtp temporarily unavailable")
        self.sent.append((str(message["From"]), list(envelope_recipients), message.as_bytes()))


def _plain_raw() -> bytes:
    return (Path(__file__).parent / "fixtures" / "plain_text.eml").read_bytes()


def _leak_raw() -> bytes:
    return (Path(__file__).parent / "fixtures" / "address_leak.eml").read_bytes()


def _config(tmp_path: Path, live: bool = False, allowed_domains: str = '["candidates.edu"]'):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f"""
[gmail]
username = "private.user@gmail.com"
imap_host = "imap.gmail.com"
imap_port = 993
all_mail_folder = "[Gmail]/All Mail"
search_query = "label:relay/pending -label:relay/sent -in:spam -in:trash"
label_pending = "Relay/pending"
label_sent = "Relay/sent"
label_error = "Relay/error"
timeout_seconds = 5
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
timeout_seconds = 5
keychain_service = "research-relay-proton-smtp"
ca_file = ""
allow_insecure_tls = false

[relay]
live_delivery = {str(live).lower()}
allow_subdomains = false
allowed_domains = {allowed_domains}
colleagues = ["c1@proton.me", "c2@example.org"]
private_address = "private.user@gmail.com"
message_id_domain = "relay.local"
hmac_keychain_service = "research-relay-hmac-key"
max_messages_per_run = 10

[attachments]
max_individual_bytes = 50000
max_combined_bytes = 100000
blocked_extensions = [".exe", ".xlsm", ".zip", ".sh"]
allowed_extensions = []
on_prohibited = "skip"
quarantine_dir = "{tmp_path / "quarantine"}"

[retry]
max_attempts = 1
initial_backoff_seconds = 1
max_backoff_seconds = 4
permanent_failure_threshold = 3

[paths]
ledger = "{tmp_path / "ledger.sqlite"}"
lock_file = "{tmp_path / "relay.lock"}"
log_file = "{tmp_path / "relay.log"}"

[logging]
level = "INFO"
max_bytes = 100000
backup_count = 2
""",
        encoding="utf-8",
    )
    return load_config(cfg_path)


def test_successful_run_sends_once_and_relabels(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    imap = FakeImap({"1001": {"raw": _plain_raw(), "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert result.sent == 1
    assert smtp.sent[0][1] == ["c1@proton.me", "c2@example.org"]
    payload = smtp.sent[0][2]
    assert b"undisclosed-recipients:;" in payload
    assert b"c1@proton.me" not in payload
    assert b"Bcc:" not in payload
    assert "Relay/sent" in imap.labels["1001"]
    assert "Relay/pending" not in imap.labels["1001"]


def test_does_not_resend_when_smtp_succeeded_but_labels_need_retry(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    imap = FakeImap({"1001": {"raw": _plain_raw(), "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()

    class LabelFailImap(FakeImap):
        def apply_sent(self, gmail_msgid: str) -> None:
            raise ConnectionError("gmail label update failed")

    first = process_messages(
        cfg, imap=LabelFailImap(imap.messages), smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None
    )
    assert first.sent == 1
    assert smtp.attempts == 1

    second = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert smtp.attempts == 1
    assert second.sent == 0
    assert second.label_retries == 1
    assert "Relay/sent" in imap.labels["1001"]


def test_temporary_smtp_failure_leaves_pending(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    imap = FakeImap({"1001": {"raw": _plain_raw(), "labels": {"Relay/pending"}}})
    smtp = FakeSmtp(fail_times=99)
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert result.sent == 0
    assert result.temporary_failures >= 1
    assert "Relay/pending" in imap.labels["1001"]
    assert "Relay/sent" not in imap.labels["1001"]
    assert smtp.sent == []


def test_dry_run_neither_sends_nor_relabels(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=False)
    imap = FakeImap({"1001": {"raw": _plain_raw(), "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=True, sleeper=lambda _s: None)
    assert result.dry_run is True
    assert smtp.sent == []
    assert "Relay/pending" in imap.labels["1001"]
    assert "Relay/sent" not in imap.labels["1001"]


def test_own_relay_output_is_not_sent_again(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True, allowed_domains='["candidates.edu", "proton.me"]')
    raw = (
        b"From: relay@proton.me\r\n"
        b"Subject: Getting long 20y after today's buyback announcement\r\n"
        b"Date: Thu, 20 Aug 2026 21:55:06 +0000\r\n"
        b"Message-ID: <deadbeefcafebabe@relay.local>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Sender: US rates watch <usrateswatch@pm.me>\r\n"
        b"Date: Wed, 19 Aug 2026 17:31:32 +0000\r\n\r\n"
        b"Today Treasury announced long-end buybacks.\r\n"
    )
    imap = FakeImap({"proton:<deadbeefcafebabe@relay.local>": {"raw": raw, "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert smtp.sent == []
    assert result.sent == 0
    assert result.skipped >= 1
    assert "Relay/pending" not in imap.labels["proton:<deadbeefcafebabe@relay.local>"]


def test_disallowed_domain_is_not_sent(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    raw = _plain_raw().replace(b"alice@candidates.edu", b"eve@attacker.example")
    imap = FakeImap({"5": {"raw": raw, "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert smtp.sent == []
    assert "Relay/error" in imap.labels["5"]


def test_dry_run_allowlist_rejection_does_not_persist_ledger(tmp_path: Path) -> None:
    from research_relay.ledger import Ledger

    cfg = _config(tmp_path, live=False)
    raw = _plain_raw().replace(b"alice@candidates.edu", b"eve@attacker.example")
    imap = FakeImap({"5": {"raw": raw, "labels": {"Relay/pending"}}})
    result = process_messages(
        cfg, imap=imap, smtp=FakeSmtp(), hmac_key=b"k", dry_run=True, sleeper=lambda _s: None
    )
    assert result.permanent_failures == 1
    assert "Relay/pending" in imap.labels["5"]
    assert Ledger(cfg.paths.ledger).get("5") is None


def test_lock_prevents_overlap(tmp_path: Path) -> None:
    path = tmp_path / "relay.lock"
    first = FileLock(path)
    first.acquire()
    second = FileLock(path)
    with pytest.raises(AlreadyRunningError):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_archive_lock_does_not_block_relay_lock(tmp_path: Path) -> None:
    relay = FileLock(tmp_path / "relay.lock")
    archive = FileLock(tmp_path / "archive.lock")
    relay.acquire()
    archive.acquire()
    relay.release()
    archive.release()


def test_logs_do_not_contain_secrets_or_full_bodies(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = _config(tmp_path, live=True)
    install_logging(cfg, extra_redactions=["super-secret-password", "private.user@gmail.com"])
    caplog.set_level(logging.INFO)
    imap = FakeImap({"1001": {"raw": _leak_raw(), "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "super-secret-password" not in joined
    assert "private.user@gmail.com" not in joined.lower()
    assert "Hello private" not in joined
    assert "My private copy is" not in joined


def test_redact_log_helper() -> None:
    msg = redact_log_message(
        "user private.user@gmail.com pass=super-secret-password body=HELLO WORLD THIS IS LONG",
        ["private.user@gmail.com", "super-secret-password"],
    )
    assert "private.user@gmail.com" not in msg
    assert "super-secret-password" not in msg


def _proton_native_raw() -> bytes:
    return (Path(__file__).parent / "fixtures" / "proton_native.eml").read_bytes()


class FakeProtonImap(FakeImap):
    def __init__(self, messages: dict[str, dict], gmail_copies: list[str] | None = None):
        super().__init__(messages)
        self._copies = list(gmail_copies or [])
        self.dismissed: list[str] = []

    def search_pending(self, limit: int | None = None) -> list[str]:
        pending = [msgid for msgid in super().search_pending() if msgid not in self._copies]
        if limit is not None:
            return pending[: max(0, int(limit))]
        return pending

    def count_pending(self) -> int:
        return sum(1 for labels in self.labels.values() if "Relay/pending" in labels)

    def dismiss_gmail_copies(self, *, dry_run: bool = False) -> int:
        copies = [msgid for msgid in self._copies if "Relay/pending" in self.labels.get(msgid, set())]
        if not dry_run:
            for msgid in copies:
                self.labels[msgid].discard("Relay/pending")
                self.dismissed.append(msgid)
        return len(copies)


def test_proton_intake_sends_native_and_dismisses_gmail_copies(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    gmail = FakeImap({})
    proton = FakeProtonImap(
        {
            "proton:<native@proton.me>": {
                "raw": _proton_native_raw(),
                "labels": {"Relay/pending"},
            },
            "proton:<copy@mail.gmail.com>": {
                "raw": _plain_raw(),
                "labels": {"Relay/pending"},
            },
        },
        gmail_copies=["proton:<copy@mail.gmail.com>"],
    )
    smtp = FakeSmtp()
    result = process_messages(
        cfg,
        imap=gmail,
        smtp=smtp,
        hmac_key=b"k",
        dry_run=False,
        extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert result.sent == 1
    assert result.skipped == 1
    assert smtp.sent
    assert "Relay/sent" in proton.labels["proton:<native@proton.me>"]
    assert "Relay/pending" not in proton.labels["proton:<copy@mail.gmail.com>"]
    assert proton.dismissed == ["proton:<copy@mail.gmail.com>"]


def test_run_splits_budget_across_gmail_and_proton(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=False)
    gmail = FakeImap(
        {str(index): {"raw": _plain_raw(), "labels": {"Relay/pending"}} for index in range(8)}
    )
    proton = FakeProtonImap(
        {
            f"proton:<native-{index}@proton.me>": {
                "raw": _proton_native_raw(),
                "labels": {"Relay/pending"},
            }
            for index in range(4)
        }
    )
    result = process_messages(
        cfg,
        imap=gmail,
        smtp=FakeSmtp(),
        hmac_key=b"k",
        dry_run=True,
        extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert len(gmail.fetches) == 5
    assert len(proton.fetches) == 4
    assert result.dry_run_candidates == 9


def test_rewritten_own_output_is_not_sent(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    raw = (
        b"From: Alice <alice@candidates.edu>\r\n"
        b"Subject: looped copy\r\n"
        b"Date: Thu, 20 Aug 2026 21:55:06 +0000\r\n"
        b"Message-ID: <rewritten@proton.me>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        + stamp_line(b"k").encode("ascii")
        + b"\n\nToday Treasury announced long-end buybacks.\r\n"
    )
    imap = FakeImap({"proton:<rewritten@proton.me>": {"raw": raw, "labels": {"Relay/pending"}}})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert smtp.sent == []
    assert result.sent == 0
    assert result.skipped >= 1
    assert "Relay/pending" not in imap.labels["proton:<rewritten@proton.me>"]


def test_per_run_cap_stops_at_ten(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    imap = FakeImap({str(index): {"raw": _plain_raw(), "labels": {"Relay/pending"}} for index in range(11)})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert result.sent == 10
    assert len(smtp.sent) == 10


def test_daily_cap_stops_the_twenty_first_send(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    cfg = replace(cfg, relay=replace(cfg.relay, max_messages_per_run=25, max_messages_per_day=20))
    imap = FakeImap({str(index): {"raw": _plain_raw(), "labels": {"Relay/pending"}} for index in range(21)})
    smtp = FakeSmtp()
    result = process_messages(cfg, imap=imap, smtp=smtp, hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert result.sent == 20
    assert result.daily_cap_reached is True
    assert len(smtp.sent) == 20


def test_unchanged_proton_pending_trips_breaker(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=True)
    gmail = FakeImap({})
    proton = FakeProtonImap(
        {"proton:<native@proton.me>": {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}}
    )
    proton.count_pending = lambda: 55
    smtp = FakeSmtp()
    first = process_messages(
        cfg,
        imap=gmail,
        smtp=smtp,
        hmac_key=b"k",
        dry_run=False,
        extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert first.sent == 1
    assert first.circuit_tripped is True
    assert first.exit_code() == 1
    assert Ledger(cfg.paths.ledger).circuit_is_open()

    proton.messages["proton:<native-2@proton.me>"] = {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}
    proton.labels["proton:<native-2@proton.me>"] = {"Relay/pending"}
    smtp2 = FakeSmtp()
    second = process_messages(
        cfg,
        imap=gmail,
        smtp=smtp2,
        hmac_key=b"k",
        dry_run=False,
        extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert smtp2.sent == []
    assert second.sent == 0
    assert second.circuit_open is True
    assert second.exit_code() == 1


def test_dry_run_does_not_count_sends_or_trip_breaker(tmp_path: Path) -> None:
    cfg = _config(tmp_path, live=False)
    cfg = replace(cfg, relay=replace(cfg.relay, max_messages_per_day=1))
    gmail = FakeImap({str(index): {"raw": _plain_raw(), "labels": {"Relay/pending"}} for index in range(2)})
    proton = FakeProtonImap(
        {"proton:<native@proton.me>": {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}}
    )
    proton.count_pending = lambda: 55
    result = process_messages(
        cfg,
        imap=gmail,
        smtp=FakeSmtp(),
        hmac_key=b"k",
        dry_run=True,
        extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert result.sent == 0
    assert result.dry_run_candidates >= 1
    assert result.circuit_tripped is False
    ledger = Ledger(cfg.paths.ledger)
    assert ledger.sent_today() == 0
    assert not ledger.circuit_is_open()


def _with_archive(cfg):
    return replace(
        cfg,
        archive=replace(
            cfg.archive,
            enabled=True,
            pdf_folder_id="pdfFolder",
            docs_folder_id="docsFolder",
        ),
    )


def test_proton_native_live_run_enqueues_archive(tmp_path: Path) -> None:
    cfg = _with_archive(_config(tmp_path, live=True))
    gmail = FakeImap({})
    proton = FakeProtonImap(
        {"proton:<native@proton.me>": {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}}
    )
    result = process_messages(
        cfg, imap=gmail, smtp=FakeSmtp(), hmac_key=b"k", dry_run=False, extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert result.sent == 1
    row = Ledger(cfg.paths.ledger).get_archive("proton:<native@proton.me>")
    assert row is not None
    assert row.kind == "html"
    assert "<proton-native-plain@proton.me>" in row.message_id


def test_gmail_sourced_run_does_not_enqueue_archive(tmp_path: Path) -> None:
    cfg = _with_archive(_config(tmp_path, live=True))
    imap = FakeImap({"1001": {"raw": _plain_raw(), "labels": {"Relay/pending"}}})
    process_messages(cfg, imap=imap, smtp=FakeSmtp(), hmac_key=b"k", dry_run=False, sleeper=lambda _s: None)
    assert Ledger(cfg.paths.ledger).get_archive("1001") is None


def test_dry_run_does_not_enqueue_archive(tmp_path: Path) -> None:
    cfg = _with_archive(_config(tmp_path, live=False))
    proton = FakeProtonImap(
        {"proton:<native@proton.me>": {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}}
    )
    process_messages(
        cfg, imap=FakeImap({}), smtp=FakeSmtp(), hmac_key=b"k", dry_run=True, extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert Ledger(cfg.paths.ledger).get_archive("proton:<native@proton.me>") is None


def test_circuit_open_still_enqueues_archive(tmp_path: Path) -> None:
    cfg = _with_archive(_config(tmp_path, live=True))
    ledger = Ledger(cfg.paths.ledger)
    ledger.trip_circuit("test")
    ledger.close()
    proton = FakeProtonImap(
        {"proton:<native@proton.me>": {"raw": _proton_native_raw(), "labels": {"Relay/pending"}}}
    )
    result = process_messages(
        cfg, imap=FakeImap({}), smtp=FakeSmtp(), hmac_key=b"k", dry_run=False, extra_imaps=[proton],
        sleeper=lambda _s: None,
    )
    assert result.sent == 0
    assert result.circuit_open is True
    row = Ledger(cfg.paths.ledger).get_archive("proton:<native@proton.me>")
    assert row is not None