from email.message import EmailMessage
from pathlib import Path

from research_relay.archive_job import enqueue_proton_archive, process_archives
from research_relay.config import load_config
from research_relay.exceptions import DriveAuthError, TemporaryRelayError
from research_relay.ledger import Ledger
from research_relay.reconstruct import reconstruct_message, parse_rfc822

from tests.pdf_fixtures import minimal_pdf_bytes


def _config(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f"""
[gmail]
username = "private.user@gmail.com"
imap_host = "imap.gmail.com"
imap_port = 993
all_mail_folder = "[Gmail]/All Mail"
search_query = "label:relay/pending"
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
live_delivery = true
allow_subdomains = false
allowed_domains = ["candidates.edu"]
colleagues = ["c1@proton.me"]
private_address = "private.user@gmail.com"
message_id_domain = "relay.local"
hmac_keychain_service = "research-relay-hmac-key"
max_messages_per_run = 10

[attachments]
max_individual_bytes = 50000
max_combined_bytes = 100000
blocked_extensions = [".exe"]
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
""",
        encoding="utf-8",
    )
    from dataclasses import replace

    cfg = load_config(cfg_path)
    return replace(
        cfg,
        archive=replace(
            cfg.archive,
            enabled=True,
            pdf_folder_id="pdfFolder",
            docs_folder_id="docsFolder",
            find_failure_threshold=5,
        ),
    )


def _pdf_raw() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@candidates.edu>"
    msg["Subject"] = "CV"
    msg["Date"] = "Fri, 28 Aug 2026 12:00:00 +0000"
    msg["Message-ID"] = "<pdf@proton.me>"
    msg.set_content("see attached")
    msg.add_attachment(minimal_pdf_bytes(), maintype="application", subtype="pdf", filename="cv.pdf")
    return msg.as_bytes()


def _plain_raw() -> bytes:
    return (Path(__file__).parent / "fixtures" / "proton_native.eml").read_bytes()


class FakeImap:
    def __init__(self, messages: dict[str, bytes]):
        self.messages = messages
        self.fetches: list[str] = []

    def fetch_by_message_id(self, message_id: str) -> bytes:
        self.fetches.append(message_id)
        if message_id not in self.messages:
            raise TemporaryRelayError("proton message not found for archive")
        return self.messages[message_id]


def _drive():
    calls: list[tuple] = []
    counter = {"n": 0}

    def _id(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}{counter['n']}"

    def pdf(*args, **kwargs):
        calls.append(("pdf", args[2] if len(args) > 2 else kwargs.get("name")))
        return _id("pdf")

    def doc(*args, **kwargs):
        calls.append(("doc", args[2] if len(args) > 2 else kwargs.get("name")))
        return _id("doc")

    def html(*args, **kwargs):
        calls.append(("html", args[2] if len(args) > 2 else kwargs.get("name")))
        return _id("html")

    return calls, pdf, doc, html


def test_drain_uploads_pdf_then_gdoc(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _pdf_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<pdf@proton.me>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(
        cfg, ledger, "proton:<pdf@proton.me>", original=original, reconstructed=reconstructed
    )
    calls, pdf, doc, html = _drive()
    result = process_archives(
        cfg,
        imap=FakeImap({"<pdf@proton.me>": raw}),
        hmac_key=b"k",
        dry_run=False,
        ledger=ledger,
        access_token="tok",
        upload_pdf=pdf,
        upload_gdoc=doc,
        upload_html=html,
    )
    kinds = [item[0] for item in calls]
    assert kinds == ["pdf", "doc"]
    assert result.completed == 1
    assert ledger.archive_is_complete(ledger.get_archive("proton:<pdf@proton.me>"))


def test_drain_html_when_no_pdf(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<x>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(cfg, ledger, "proton:<x>", original=original, reconstructed=reconstructed)
    calls, pdf, doc, html = _drive()
    process_archives(
        cfg,
        imap=FakeImap({"<proton-native-plain@proton.me>": raw}),
        hmac_key=b"k",
        dry_run=False,
        ledger=ledger,
        access_token="tok",
        upload_pdf=pdf,
        upload_gdoc=doc,
        upload_html=html,
    )
    assert [item[0] for item in calls] == ["html"]
    assert calls[0][1].endswith(".html")


def test_dry_run_does_not_fetch_or_upload(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<x>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(cfg, ledger, "proton:<x>", original=original, reconstructed=reconstructed)
    imap = FakeImap({"<proton-native-plain@proton.me>": raw})
    calls, pdf, doc, html = _drive()
    process_archives(
        cfg,
        imap=imap,
        hmac_key=b"k",
        dry_run=True,
        ledger=ledger,
        access_token="tok",
        upload_pdf=pdf,
        upload_gdoc=doc,
        upload_html=html,
    )
    assert imap.fetches == []
    assert calls == []


def test_retries_doc_only_when_pdf_id_exists(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _pdf_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<pdf@proton.me>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(
        cfg, ledger, "proton:<pdf@proton.me>", original=original, reconstructed=reconstructed
    )
    row = ledger.get_archive("proton:<pdf@proton.me>")
    name = row.expected_names[0]
    ledger.record_pdf_id("proton:<pdf@proton.me>", name, "existing-pdf")
    calls, pdf, doc, html = _drive()
    process_archives(
        cfg,
        imap=FakeImap({"<pdf@proton.me>": raw}),
        hmac_key=b"k",
        dry_run=False,
        ledger=ledger,
        access_token="tok",
        upload_pdf=pdf,
        upload_gdoc=doc,
        upload_html=html,
    )
    assert [item[0] for item in calls] == ["doc"]


def test_imap_miss_becomes_unrecoverable_at_threshold(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg = __import__("dataclasses").replace(
        cfg, archive=__import__("dataclasses").replace(cfg.archive, find_failure_threshold=2)
    )
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<x>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(cfg, ledger, "proton:<x>", original=original, reconstructed=reconstructed)
    imap = FakeImap({})
    calls, pdf, doc, html = _drive()
    process_archives(
        cfg, imap=imap, hmac_key=b"k", dry_run=False, ledger=ledger, access_token="tok",
        upload_pdf=pdf, upload_gdoc=doc, upload_html=html,
    )
    process_archives(
        cfg, imap=imap, hmac_key=b"k", dry_run=False, ledger=ledger, access_token="tok",
        upload_pdf=pdf, upload_gdoc=doc, upload_html=html,
    )
    row = ledger.get_archive("proton:<x>")
    assert row.unrecoverable is True
    assert calls == []


def test_drive_auth_error_is_operational(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<x>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(cfg, ledger, "proton:<x>", original=original, reconstructed=reconstructed)

    def boom(*args, **kwargs):
        raise DriveAuthError("Drive HTTP 401")

    result = process_archives(
        cfg,
        imap=FakeImap({"<proton-native-plain@proton.me>": raw}),
        hmac_key=b"k",
        dry_run=False,
        ledger=ledger,
        access_token="tok",
        upload_pdf=boom,
        upload_gdoc=boom,
        upload_html=boom,
    )
    assert result.operational_failures == 1
    assert result.exit_code() == 1


def test_force_clears_ids_and_reuploads(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _pdf_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<pdf@proton.me>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(
        cfg, ledger, "proton:<pdf@proton.me>", original=original, reconstructed=reconstructed
    )
    row = ledger.get_archive("proton:<pdf@proton.me>")
    ledger.record_pdf_id("proton:<pdf@proton.me>", row.expected_names[0], "old-pdf")
    ledger.record_doc_id("proton:<pdf@proton.me>", row.expected_names[0], "old-doc")
    calls, pdf, doc, html = _drive()
    process_archives(
        cfg,
        imap=FakeImap({"<pdf@proton.me>": raw}),
        hmac_key=b"k",
        dry_run=False,
        ledger=ledger,
        access_token="tok",
        upload_pdf=pdf,
        upload_gdoc=doc,
        upload_html=html,
        force_key="proton:<pdf@proton.me>",
    )
    assert [item[0] for item in calls] == ["pdf", "doc"]


def test_enqueue_recent_writes_new_rows_and_skips_existing(tmp_path: Path) -> None:
    from research_relay.archive_job import enqueue_recent_archives

    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()
    original = parse_rfc822(raw)
    from research_relay.archive_job import reconstruction_settings

    reconstructed = reconstruct_message(
        original, gmail_msgid="proton:<already>", settings=reconstruction_settings(cfg, b"k")
    )
    enqueue_proton_archive(cfg, ledger, "proton:<already>", original=original, reconstructed=reconstructed)

    class RecentImap:
        def __init__(self) -> None:
            self.messages = {
                "proton:<already>": raw,
                "proton:<proton-native-plain@proton.me>": raw,
            }

        def collect_recent_native(self, *, hours=None, since=None, limit=None, now=None):
            return list(self.messages)

        def fetch_message(self, key: str) -> bytes:
            return self.messages[key]

    result = enqueue_recent_archives(
        cfg, imap=RecentImap(), hmac_key=b"k", hours=48, limit=20, dry_run=False, ledger=ledger
    )
    assert result.scanned == 2
    assert result.skipped_existing == 1
    assert result.enqueued == 1
    assert ledger.get_archive("proton:<proton-native-plain@proton.me>") is not None


def test_enqueue_recent_dry_run_does_not_write(tmp_path: Path) -> None:
    from research_relay.archive_job import enqueue_recent_archives

    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()

    class RecentImap:
        def collect_recent_native(self, *, hours=None, since=None, limit=None, now=None):
            return ["proton:<proton-native-plain@proton.me>"]

        def fetch_message(self, key: str) -> bytes:
            return raw

    result = enqueue_recent_archives(
        cfg, imap=RecentImap(), hmac_key=b"k", hours=48, limit=20, dry_run=True, ledger=ledger
    )
    assert result.enqueued == 1
    assert result.dry_run is True
    assert ledger.get_archive("proton:<proton-native-plain@proton.me>") is None


def test_enqueue_recent_respects_limit(tmp_path: Path) -> None:
    from research_relay.archive_job import enqueue_recent_archives

    cfg = _config(tmp_path)
    ledger = Ledger(cfg.paths.ledger)
    raw = _plain_raw()

    class RecentImap:
        def collect_recent_native(self, *, hours=None, since=None, limit=None, now=None):
            return ["proton:<a>", "proton:<b>"]

        def fetch_message(self, key: str) -> bytes:
            return raw

    result = enqueue_recent_archives(
        cfg, imap=RecentImap(), hmac_key=b"k", hours=48, limit=1, dry_run=False, ledger=ledger
    )
    assert result.enqueued == 1
    assert result.skipped_limit == 1
    assert ledger.get_archive("proton:<a>") is not None
    assert ledger.get_archive("proton:<b>") is None
