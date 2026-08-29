from pathlib import Path

import pytest

from research_relay.config import ConfigError, load_config


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
colleagues = ["c1@proton.me"]
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


def test_loads_valid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.gmail.username == "private.user@gmail.com"
    assert cfg.relay.live_delivery is False
    assert cfg.proton.mode == "starttls"
    assert cfg.auth.method == "app_password"
    assert cfg.proton.imap_host == "127.0.0.1"
    assert cfg.proton.imap_port == 1143
    assert cfg.proton.folder_pending == r"Labels/Relay\/pending"
    assert cfg.relay.max_age_days == 0
    assert cfg.relay.max_messages_per_run == 20
    assert cfg.relay.max_messages_per_day == 40


def test_rejects_unknown_auth_method(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL.replace("app_password", "not-a-method"), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_rejects_bare_tld_allowlist(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL.replace('["candidates.edu"]', '["edu"]'), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_rejects_insecure_tls_without_localhost(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    text = MINIMAL.replace('smtp_host = "127.0.0.1"', 'smtp_host = "smtp.example.com"')
    text = text.replace("allow_insecure_tls = false", "allow_insecure_tls = true")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_oauth2_requires_credential_paths(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL.replace("app_password", "oauth2"), encoding="utf-8")
    with pytest.raises(ConfigError, match="credentials_file"):
        load_config(path)


def test_loads_oauth2_paths(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    extra = """
credentials_file = "~/gmail-oauth-client.json"
token_file = "~/gmail-oauth-token.json"
redirect_port = 8765
"""
    path.write_text(
        MINIMAL.replace("method = \"app_password\"", 'method = "oauth2"\n' + extra),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.auth.method == "oauth2"
    assert cfg.auth.credentials_file.name == "gmail-oauth-client.json"
    assert cfg.auth.token_file.name == "gmail-oauth-token.json"
    assert cfg.auth.redirect_port == 8765


def test_day_cap_defaults_to_twice_per_run(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL.replace("max_messages_per_run = 20", "max_messages_per_run = 10"), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.relay.max_messages_per_run == 10
    assert cfg.relay.max_messages_per_day == 20


def test_day_cap_can_be_set_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        MINIMAL.replace(
            "max_messages_per_run = 20",
            "max_messages_per_run = 10\nmax_messages_per_day = 15",
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.relay.max_messages_per_day == 15


def test_rejects_non_positive_message_caps(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL.replace("max_messages_per_run = 20", "max_messages_per_run = 0"), encoding="utf-8")
    with pytest.raises(ConfigError, match="max_messages_per_run"):
        load_config(path)


def test_archive_defaults_disabled_when_section_omitted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.archive.enabled is False
    assert cfg.archive.pdf_folder_id == ""
    assert cfg.archive.docs_folder_id == ""
    assert cfg.archive.max_retries_per_run == 20
    assert cfg.archive.find_failure_threshold == 5
    assert cfg.paths.archive_lock_file == Path("/tmp/archive.lock")


def test_archive_enabled_requires_folder_ids(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(MINIMAL + "\n[archive]\nenabled = true\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="folder"):
        load_config(path)


def test_archive_enabled_requires_oauth2(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        MINIMAL
        + """
[archive]
enabled = true
pdf_folder_id = "pdfid"
docs_folder_id = "docsid"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="oauth2"):
        load_config(path)


def test_loads_archive_section_with_oauth2(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    extra = """
credentials_file = "~/gmail-oauth-client.json"
token_file = "~/gmail-oauth-token.json"
"""
    body = MINIMAL.replace('method = "app_password"', 'method = "oauth2"\n' + extra)
    body += """
[archive]
enabled = true
pdf_folder_id = "pdfFolderId"
docs_folder_id = "docsFolderId"
max_retries_per_run = 7
find_failure_threshold = 3
"""
    path.write_text(body, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.archive.enabled is True
    assert cfg.archive.pdf_folder_id == "pdfFolderId"
    assert cfg.archive.docs_folder_id == "docsFolderId"
    assert cfg.archive.max_retries_per_run == 7
    assert cfg.archive.find_failure_threshold == 3


def test_archive_lock_file_can_be_set(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        MINIMAL.replace(
            'lock_file = "/tmp/relay.lock"',
            'lock_file = "/tmp/relay.lock"\narchive_lock_file = "/tmp/custom-archive.lock"',
        ),
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.paths.archive_lock_file == Path("/tmp/custom-archive.lock")
