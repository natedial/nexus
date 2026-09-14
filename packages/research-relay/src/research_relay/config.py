from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from research_relay.exceptions import ConfigError as ConfigError


@dataclass(frozen=True)
class GmailConfig:
    username: str
    imap_host: str
    imap_port: int
    all_mail_folder: str
    search_query: str
    label_pending: str
    label_sent: str
    label_error: str
    timeout_seconds: float
    keychain_service: str


@dataclass(frozen=True)
class AuthConfig:
    method: str
    credentials_file: Path | None
    token_file: Path | None
    redirect_port: int


@dataclass(frozen=True)
class ProtonConfig:
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    mode: str
    username: str
    from_address: str
    reply_to: str
    timeout_seconds: float
    keychain_service: str
    ca_file: str
    allow_insecure_tls: bool
    folder_pending: str
    folder_sent: str
    folder_error: str
    folder_inbox: str


@dataclass(frozen=True)
class RelayConfig:
    live_delivery: bool
    allow_subdomains: bool
    allowed_domains: list[str]
    colleagues: list[str]
    private_address: str
    message_id_domain: str
    hmac_keychain_service: str
    max_messages_per_run: int
    max_messages_per_day: int
    max_age_days: int


@dataclass(frozen=True)
class AttachmentConfig:
    max_individual_bytes: int
    max_combined_bytes: int
    blocked_extensions: tuple[str, ...]
    allowed_extensions: tuple[str, ...]
    on_prohibited: str
    quarantine_dir: str


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int
    initial_backoff_seconds: float
    max_backoff_seconds: float
    permanent_failure_threshold: int


@dataclass(frozen=True)
class PathsConfig:
    ledger: Path
    lock_file: Path
    log_file: Path
    archive_lock_file: Path


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class AlertsConfig:
    enabled: bool
    channel: str
    to: str
    imessage_to: str
    cooldown_seconds: int
    dry_run: bool


@dataclass(frozen=True)
class ArchiveConfig:
    enabled: bool
    pdf_folder_id: str
    docs_folder_id: str
    max_retries_per_run: int
    find_failure_threshold: int


@dataclass(frozen=True)
class AppConfig:
    gmail: GmailConfig
    auth: AuthConfig
    proton: ProtonConfig
    relay: RelayConfig
    attachments: AttachmentConfig
    retry: RetryConfig
    paths: PathsConfig
    logging: LoggingConfig
    alerts: AlertsConfig
    archive: ArchiveConfig
    source_path: Path


def _path(value: str) -> Path:
    return Path(str(value)).expanduser()


def _optional_path(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text).expanduser()


def _max_age_days(value: object) -> int:
    days = int(value or 0)
    if days < 0:
        raise ConfigError("relay.max_age_days must be >= 0")
    return days


def _positive_int(value: object, name: str, default: int) -> int:
    if value is None or value == "":
        number = default
    else:
        number = int(value)
    if number < 1:
        raise ConfigError(f"{name} must be >= 1")
    return number


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    try:
        gmail = data["gmail"]
        auth = data.get("auth", {"method": "app_password"})
        proton = data["proton"]
        relay = data["relay"]
        attachments = data["attachments"]
        retry = data["retry"]
        paths = data["paths"]
        logging_cfg = data.get("logging", {})
    except KeyError as exc:
        raise ConfigError(f"missing config section or key: {exc}") from exc

    method = str(auth.get("method", "app_password")).lower()
    if method not in {"app_password", "oauth2"}:
        raise ConfigError("auth.method must be app_password or oauth2")

    credentials_file = _optional_path(auth.get("credentials_file", ""))
    token_file = _optional_path(auth.get("token_file", ""))
    redirect_port = int(auth.get("redirect_port", 0) or 0)
    if method == "oauth2":
        if credentials_file is None:
            raise ConfigError("auth.credentials_file is required when auth.method = oauth2")
        if token_file is None:
            raise ConfigError("auth.token_file is required when auth.method = oauth2")

    mode = str(proton.get("mode", "starttls")).lower()
    if mode not in {"starttls", "tls"}:
        raise ConfigError("proton.mode must be starttls or tls")

    allowed_domains = [str(item).strip().lower().rstrip(".") for item in relay.get("allowed_domains", [])]
    if not allowed_domains:
        raise ConfigError("relay.allowed_domains must not be empty")
    for domain in allowed_domains:
        if "." not in domain or domain.startswith(".") or "@" in domain:
            raise ConfigError(f"allowed domain {domain!r} is not a full DNS name")

    colleagues = [str(item).strip() for item in relay.get("colleagues", []) if str(item).strip()]
    if not colleagues:
        raise ConfigError("relay.colleagues must not be empty")

    on_prohibited = str(attachments.get("on_prohibited", "skip")).lower()
    if on_prohibited not in {"skip", "quarantine"}:
        raise ConfigError("attachments.on_prohibited must be skip or quarantine")

    allow_insecure = bool(proton.get("allow_insecure_tls", False))
    smtp_host = str(proton["smtp_host"]).strip()
    if allow_insecure and smtp_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("allow_insecure_tls is only permitted for localhost SMTP")

    per_run = _positive_int(relay.get("max_messages_per_run", 10), "relay.max_messages_per_run", 10)
    per_day = _positive_int(relay.get("max_messages_per_day"), "relay.max_messages_per_day", per_run * 2)

    alerts = data.get("alerts", {})
    channel = str(alerts.get("channel", "email")).lower()
    if channel not in {"email", "imessage", "both"}:
        raise ConfigError("alerts.channel must be email, imessage, or both")
    cooldown_seconds = int(alerts.get("cooldown_seconds", 21600) or 0)
    if cooldown_seconds < 0:
        raise ConfigError("alerts.cooldown_seconds must be >= 0")

    archive_cfg = data.get("archive", {})
    archive_enabled = bool(archive_cfg.get("enabled", False))
    pdf_folder_id = str(archive_cfg.get("pdf_folder_id", "")).strip()
    docs_folder_id = str(archive_cfg.get("docs_folder_id", "")).strip()
    archive_retries = _positive_int(
        archive_cfg.get("max_retries_per_run"), "archive.max_retries_per_run", 20
    )
    find_failure_threshold = _positive_int(
        archive_cfg.get("find_failure_threshold"), "archive.find_failure_threshold", 5
    )
    if archive_enabled:
        if not pdf_folder_id or not docs_folder_id:
            raise ConfigError("archive.pdf_folder_id and archive.docs_folder_id are required when archive.enabled = true")
        if method != "oauth2":
            raise ConfigError("archive.enabled requires auth.method = oauth2")

    lock_file = _path(paths["lock_file"])
    archive_lock_raw = str(paths.get("archive_lock_file", "")).strip()
    archive_lock_file = _path(archive_lock_raw) if archive_lock_raw else lock_file.with_name("archive.lock")

    return AppConfig(
        gmail=GmailConfig(
            username=str(gmail["username"]),
            imap_host=str(gmail.get("imap_host", "imap.gmail.com")),
            imap_port=int(gmail.get("imap_port", 993)),
            all_mail_folder=str(gmail.get("all_mail_folder", "[Gmail]/All Mail")),
            search_query=str(
                gmail.get(
                    "search_query",
                    "label:relay/pending -label:relay/sent -in:spam -in:trash",
                )
            ),
            label_pending=str(gmail.get("label_pending", "Relay/pending")),
            label_sent=str(gmail.get("label_sent", "Relay/sent")),
            label_error=str(gmail.get("label_error", "Relay/error")),
            timeout_seconds=float(gmail.get("timeout_seconds", 120)),
            keychain_service=str(gmail.get("keychain_service", "research-relay-gmail")),
        ),
        auth=AuthConfig(
            method=method,
            credentials_file=credentials_file,
            token_file=token_file,
            redirect_port=redirect_port,
        ),
        proton=ProtonConfig(
            smtp_host=smtp_host,
            smtp_port=int(proton.get("smtp_port", 1025)),
            imap_host=str(proton.get("imap_host") or smtp_host).strip(),
            imap_port=int(proton.get("imap_port", 1143)),
            mode=mode,
            username=str(proton["username"]),
            from_address=str(proton["from_address"]),
            reply_to=str(proton["reply_to"]),
            timeout_seconds=float(proton.get("timeout_seconds", 30)),
            keychain_service=str(proton.get("keychain_service", "research-relay-proton-smtp")),
            ca_file=str(proton.get("ca_file", "")),
            allow_insecure_tls=allow_insecure,
            folder_pending=str(proton.get("folder_pending", r"Labels/Relay\/pending")),
            folder_sent=str(proton.get("folder_sent", r"Labels/Relay\/sent")),
            folder_error=str(proton.get("folder_error", r"Labels/Relay\/error")),
            folder_inbox=str(proton.get("folder_inbox", "INBOX")),
        ),
        relay=RelayConfig(
            live_delivery=bool(relay.get("live_delivery", False)),
            allow_subdomains=bool(relay.get("allow_subdomains", False)),
            allowed_domains=allowed_domains,
            colleagues=colleagues,
            private_address=str(relay["private_address"]).strip(),
            message_id_domain=str(relay.get("message_id_domain", "relay.local")),
            hmac_keychain_service=str(relay.get("hmac_keychain_service", "research-relay-hmac-key")),
            max_messages_per_run=per_run,
            max_messages_per_day=per_day,
            max_age_days=_max_age_days(relay.get("max_age_days", 0)),
        ),
        attachments=AttachmentConfig(
            max_individual_bytes=int(attachments["max_individual_bytes"]),
            max_combined_bytes=int(attachments["max_combined_bytes"]),
            blocked_extensions=tuple(str(item) for item in attachments.get("blocked_extensions", [])),
            allowed_extensions=tuple(str(item) for item in attachments.get("allowed_extensions", [])),
            on_prohibited=on_prohibited,
            quarantine_dir=str(attachments.get("quarantine_dir", "")),
        ),
        retry=RetryConfig(
            max_attempts=int(retry.get("max_attempts", 3)),
            initial_backoff_seconds=float(retry.get("initial_backoff_seconds", 2)),
            max_backoff_seconds=float(retry.get("max_backoff_seconds", 60)),
            permanent_failure_threshold=int(retry.get("permanent_failure_threshold", 5)),
        ),
        paths=PathsConfig(
            ledger=_path(paths["ledger"]),
            lock_file=lock_file,
            log_file=_path(paths["log_file"]),
            archive_lock_file=archive_lock_file,
        ),
        logging=LoggingConfig(
            level=str(logging_cfg.get("level", "INFO")).upper(),
            max_bytes=int(logging_cfg.get("max_bytes", 1_048_576)),
            backup_count=int(logging_cfg.get("backup_count", 5)),
        ),
        alerts=AlertsConfig(
            enabled=bool(alerts.get("enabled", False)),
            channel=channel,
            to=str(alerts.get("to", "")).strip(),
            imessage_to=str(alerts.get("imessage_to", "")).strip(),
            cooldown_seconds=cooldown_seconds,
            dry_run=bool(alerts.get("dry_run", False)),
        ),
        archive=ArchiveConfig(
            enabled=archive_enabled,
            pdf_folder_id=pdf_folder_id,
            docs_folder_id=docs_folder_id,
            max_retries_per_run=archive_retries,
            find_failure_threshold=find_failure_threshold,
        ),
        source_path=config_path,
    )
