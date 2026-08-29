from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from research_relay.alerts import AlertEvent, classify_exception, classify_run_result, maybe_alert, notify
from research_relay.auth import build_auth
from research_relay.config import load_config
from research_relay.exceptions import AlreadyRunningError, ConfigError, KeychainError, RelayError
from research_relay.gmail_imap import GmailImap
from research_relay.health import run_health
from research_relay.keychain import apply_secrets_file, get_generic_password, secrets_path_for_config
from research_relay.lock import FileLock
from research_relay.logging_setup import install_logging
from research_relay.proton_imap import ProtonImap
from research_relay.proton_smtp import ProtonSmtp
from research_relay.runner import process_messages
from research_relay.runtime import clear_max_runtime, install_max_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-relay",
        description="Gmail to Proton Bridge email relay",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to TOML config (default: $RESEARCH_RELAY_CONFIG or ~/.config/research-relay/config.toml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Process pending Gmail messages")
    run_p.add_argument("--dry-run", action="store_true", help="Fetch and sanitize only; do not send or relabel")
    run_p.add_argument(
        "--live",
        action="store_true",
        help="Enable live SMTP delivery and Gmail label changes (also requires live_delivery = true)",
    )
    run_p.add_argument(
        "--max-messages",
        type=int,
        default=None,
        metavar="N",
        help="Override relay.max_messages_per_run for this invocation",
    )
    run_p.add_argument(
        "--max-runtime",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Abort the run after N seconds even if IMAP/SSL is blocked (LaunchAgent watchdog)",
    )

    sub.add_parser("health", help="Check config, Keychain, SQLite, IMAP, SMTP, and circuit breaker without sending mail")
    sub.add_parser("breaker-reset", help="Clear a tripped send circuit breaker")
    archive_p = sub.add_parser("archive", help="Upload Proton-native PDFs/HTML to Google Drive")
    archive_p.add_argument("--dry-run", action="store_true", help="List incomplete archive rows; do not fetch or upload")
    archive_p.add_argument(
        "--live",
        action="store_true",
        help="Enable Drive uploads (also requires live_delivery = true)",
    )
    archive_p.add_argument(
        "--max-runtime",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Abort after N seconds",
    )
    archive_p.add_argument(
        "--force",
        action="store_true",
        help="Clear stored Drive ids for --key and upload again",
    )
    archive_p.add_argument("--key", default=None, help="Archive ledger key (proton:...)")
    archive_p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max incomplete rows this run (default: archive.max_retries_per_run)",
    )
    enqueue_p = sub.add_parser(
        "archive-enqueue",
        help="Scan Proton sent/pending for recent native mail and enqueue Drive archive rows",
    )
    enqueue_p.add_argument(
        "--hours",
        type=int,
        default=None,
        metavar="N",
        help="Look back N hours using Date (default: 48 when --since is omitted)",
    )
    enqueue_p.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help="Include mail with Date on or after this local calendar day",
    )
    enqueue_p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max new archive rows (default: no cap)",
    )
    enqueue_p.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching mail; do not write archive rows",
    )
    sub.add_parser("archive-status", help="List incomplete and unrecoverable Drive archive rows")
    sub.add_parser(
        "auth",
        help="One-time Google OAuth consent for Gmail IMAP (opens a browser, saves a refresh token)",
    )
    sub.add_parser(
        "alert-test",
        help="Send a one-shot ops alert (respects alerts.dry_run; does not use relay.colleagues)",
    )
    return parser


def parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    raw = list(sys.argv[1:] if argv is None else argv)
    config, remaining = _extract_config_option(raw)
    args = build_parser().parse_args(remaining)
    if config is not None:
        args.config = config
    return args


def _extract_config_option(argv: list[str]) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    config: str | None = None
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--config":
            if index + 1 >= len(argv):
                remaining.extend(argv[index:])
                break
            config = argv[index + 1]
            index += 2
            continue
        if argument.startswith("--config="):
            config = argument.split("=", 1)[1]
            index += 1
            continue
        remaining.append(argument)
        index += 1
    return config, remaining


def main(argv: list[str] | None = None) -> int:
    args = parse_cli(argv)
    try:
        config_path = _resolve_config(args.config)
        apply_secrets_file(secrets_path_for_config(config_path))
        cfg = load_config(config_path)
        if args.command == "run" and getattr(args, "max_messages", None) is not None:
            if args.max_messages < 1:
                raise ConfigError("--max-messages must be >= 1")
            cfg = replace(cfg, relay=replace(cfg.relay, max_messages_per_run=args.max_messages))
        if args.command == "run" and getattr(args, "max_runtime", None) is not None:
            if args.max_runtime < 1:
                raise ConfigError("--max-runtime must be >= 1")
        if args.command == "archive" and getattr(args, "limit", None) is not None:
            if args.limit < 1:
                raise ConfigError("--limit must be >= 1")
            cfg = replace(cfg, archive=replace(cfg.archive, max_retries_per_run=args.limit))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except KeychainError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.command == "breaker-reset":
        from research_relay.ledger import Ledger

        ledger = Ledger(cfg.paths.ledger)
        ledger.reset_circuit()
        ledger.close()
        print("circuit breaker reset")
        return 0

    if args.command == "health":
        report = run_health(cfg)
        for check in report.checks:
            status = "ok" if check.ok else "FAIL"
            print(f"{status:4}  {check.name}: {check.detail}")
        return 0 if report.ok else 1

    if args.command == "auth":
        if cfg.auth.method != "oauth2":
            print("config error: auth.method must be oauth2 to run the Google consent flow", file=sys.stderr)
            return 2
        try:
            from research_relay.oauth import run_authorization_flow

            run_authorization_flow(
                credentials_file=cfg.auth.credentials_file,
                token_file=cfg.auth.token_file,
                redirect_port=cfg.auth.redirect_port,
            )
            return 0
        except (ConfigError, RelayError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

    import os

    extra = [
        os.environ[name].strip()
        for name in ("RESEARCH_RELAY_HMAC_KEY", "RESEARCH_RELAY_PROTON_PASSWORD")
        if os.environ.get(name, "").strip()
    ]

    if args.command == "alert-test":
        logger = install_logging(cfg, extra_redactions=extra)
        password = _proton_password(cfg, required=False)
        event = AlertEvent("test", "manual test from research-relay alert-test")
        sent = notify(cfg, event, proton_password=password, force=True)
        if cfg.alerts.dry_run:
            logger.info("alert-test dry-run kind=test")
            print("alert-test dry-run: would send kind=test (no SMTP/Messages)")
            return 0
        if sent:
            print("alert-test sent")
            return 0
        print(
            "alert-test not sent (set alerts.enabled = true and alerts.to or alerts.imessage_to)",
            file=sys.stderr,
        )
        logger.warning("alert-test not sent")
        return 1

    if args.command == "archive-status":
        return _archive_status(cfg)

    if args.command == "archive-enqueue":
        logger = install_logging(cfg, extra_redactions=extra)
        try:
            since_raw = getattr(args, "since", None)
            hours_raw = getattr(args, "hours", None)
            if since_raw and hours_raw is not None:
                raise ConfigError("use --since or --hours, not both")
            since = None
            hours = None
            if since_raw:
                from research_relay.age import parse_since_day

                try:
                    since = parse_since_day(since_raw)
                except ValueError as exc:
                    raise ConfigError(str(exc)) from exc
            else:
                hours = int(hours_raw) if hours_raw is not None else 48
                if hours < 1:
                    raise ConfigError("--hours must be >= 1")
            limit = getattr(args, "limit", None)
            if limit is not None:
                limit = int(limit)
                if limit < 1:
                    raise ConfigError("--limit must be >= 1")
        except ConfigError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        args.hours = hours
        args.since_dt = since
        args.limit = limit
        return _run_archive_enqueue(args, cfg, logger)

    if args.command == "archive":
        logger = install_logging(cfg, extra_redactions=extra)
        try:
            dry_run = _want_dry_run(args, cfg)
        except ConfigError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
        if getattr(args, "force", False) and not getattr(args, "key", None):
            print("config error: --force requires --key", file=sys.stderr)
            return 2
        return _run_archive(args, cfg, dry_run, logger)

    logger = install_logging(cfg, extra_redactions=extra)
    try:
        dry_run = _want_dry_run(args, cfg)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if dry_run:
        logger.info(
            "starting dry-run max_age_days=%s max_messages=%s max_messages_per_day=%s",
            cfg.relay.max_age_days,
            cfg.relay.max_messages_per_run,
            cfg.relay.max_messages_per_day,
        )
    else:
        logger.info(
            "starting live delivery run max_age_days=%s max_messages=%s max_messages_per_day=%s",
            cfg.relay.max_age_days,
            cfg.relay.max_messages_per_run,
            cfg.relay.max_messages_per_day,
        )
        if cfg.alerts.enabled and not cfg.alerts.to and not cfg.alerts.imessage_to:
            logger.warning(
                "alerts enabled but no alerts.to or alerts.imessage_to; failures will stay silent"
            )

    lock = FileLock(cfg.paths.lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        logger.info("another relay process is running; exiting")
        return 0

    max_runtime = getattr(args, "max_runtime", None)
    if max_runtime:
        logger.info("max runtime %ss", max_runtime)
        install_max_runtime(max_runtime)

    imap = None
    proton_imap = None
    smtp = None
    alert_event: AlertEvent | None = None
    proton_password = None
    proton_skip_event: AlertEvent | None = None
    try:
        gmail_auth = _gmail_auth(cfg)
        hmac_key = get_generic_password(cfg.relay.hmac_keychain_service, "hmac").encode("utf-8")
        imap = GmailImap(cfg, gmail_auth)
        logger.info("connecting gmail imap")
        imap.connect()
        smtp = None
        proton_password = _proton_password(cfg, required=not dry_run)
        if proton_password:
            try:
                proton_imap = ProtonImap(cfg, proton_password, hmac_key=hmac_key)
                logger.info("connecting proton imap")
                proton_imap.connect()
            except RelayError as exc:
                logger.warning("proton imap skipped: %s", exc)
                proton_skip_event = classify_exception(exc)
                proton_imap = None
        else:
            logger.info("proton imap skipped (no password)")
        if not dry_run:
            smtp = ProtonSmtp(cfg.proton, proton_password or "")
            smtp.connect()
        extra = [proton_imap] if proton_imap is not None else []
        result = process_messages(
            cfg,
            imap=imap,
            smtp=smtp,
            hmac_key=hmac_key,
            dry_run=dry_run,
            extra_imaps=extra,
        )
        logger.info(
            "run complete sent=%s label_retries=%s temp=%s perm=%s ops=%s skipped=%s dry=%s",
            result.sent,
            result.label_retries,
            result.temporary_failures,
            result.permanent_failures,
            result.operational_failures,
            result.skipped,
            result.dry_run_candidates,
        )
        if result.exit_code() != 0:
            alert_event = classify_run_result(result)
        elif proton_skip_event is not None:
            alert_event = proton_skip_event
        else:
            alert_event = classify_run_result(result)
        return result.exit_code()
    except SystemExit:
        alert_event = AlertEvent("max_runtime", "max runtime exceeded")
        return 1
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except KeychainError as exc:
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except RelayError as exc:
        logger.error("run failed: %s", exc)
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 1
    finally:
        clear_max_runtime()
        for client in (smtp, proton_imap, imap):
            if client is None:
                continue
            try:
                client.close()
            except Exception:
                pass
        lock.release()
        maybe_alert(cfg, alert_event, proton_password, skip=dry_run)


def _archive_status(cfg) -> int:
    from research_relay.ledger import Ledger

    ledger = Ledger(cfg.paths.ledger)
    try:
        incomplete = ledger.list_incomplete(limit=10_000)
        unrecoverable = ledger.count_unrecoverable()
        print(f"incomplete={len(incomplete)} unrecoverable={unrecoverable}")
        for row in incomplete:
            missing = []
            if row.kind == "html" and not row.html_id:
                missing.append("html")
            for name in row.expected_names:
                if not row.pdf_ids.get(name):
                    missing.append(f"pdf:{name}")
                if not row.doc_ids.get(name):
                    missing.append(f"doc:{name}")
            print(f"  {row.gmail_msgid} missing={','.join(missing) or '-'} error={row.last_error}")
        for row in ledger.list_unrecoverable():
            print(f"  UNRECOVERABLE {row.gmail_msgid} error={row.last_error}")
        return 0
    finally:
        ledger.close()


def _run_archive_enqueue(args, cfg, logger) -> int:
    from research_relay.archive_job import enqueue_recent_archives

    if not cfg.archive.enabled:
        logger.info("archive disabled; exiting")
        print("archive disabled (archive.enabled = false)")
        return 0

    dry_run = bool(getattr(args, "dry_run", False))
    hours = getattr(args, "hours", None)
    since = getattr(args, "since_dt", None)
    limit = getattr(args, "limit", None)

    lock = FileLock(cfg.paths.archive_lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        logger.info("another archive process is running; exiting")
        return 0

    proton_imap = None
    proton_password = None
    alert_event: AlertEvent | None = None
    try:
        hmac_key = get_generic_password(cfg.relay.hmac_keychain_service, "hmac").encode("utf-8")
        proton_password = _proton_password(cfg, required=True)
        proton_imap = ProtonImap(cfg, proton_password, hmac_key=hmac_key)
        logger.info(
            "connecting proton imap for archive-enqueue hours=%s since=%s limit=%s",
            hours,
            since.date().isoformat() if since is not None else None,
            limit,
        )
        proton_imap.connect()
        result = enqueue_recent_archives(
            cfg,
            imap=proton_imap,
            hmac_key=hmac_key,
            hours=hours,
            since=since,
            limit=limit,
            dry_run=dry_run,
        )
        logger.info(
            "archive-enqueue scanned=%s enqueued=%s skipped_existing=%s skipped_domain=%s skipped_other=%s skipped_limit=%s dry=%s",
            result.scanned,
            result.enqueued,
            result.skipped_existing,
            result.skipped_domain,
            result.skipped_other,
            result.skipped_limit,
            result.dry_run,
        )
        window = (
            f"since={since.date().isoformat()}"
            if since is not None
            else f"hours={hours}"
        )
        print(
            f"scanned={result.scanned} enqueued={result.enqueued} "
            f"skipped_existing={result.skipped_existing} skipped_domain={result.skipped_domain} "
            f"skipped_other={result.skipped_other} skipped_limit={result.skipped_limit} "
            f"{window} dry_run={result.dry_run}"
        )
        for note in result.notes:
            print(note)
        return 0
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except KeychainError as exc:
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except RelayError as exc:
        logger.error("archive-enqueue failed: %s", exc)
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 1
    finally:
        if proton_imap is not None:
            try:
                proton_imap.close()
            except Exception:
                pass
        lock.release()
        maybe_alert(cfg, alert_event, proton_password, skip=dry_run)


def _run_archive(args, cfg, dry_run: bool, logger) -> int:
    from research_relay.archive_job import process_archives
    from research_relay.ledger import Ledger
    from research_relay.oauth import OAuthTokenStore

    if not cfg.archive.enabled:
        logger.info("archive disabled; exiting")
        print("archive disabled (archive.enabled = false)")
        return 0

    lock = FileLock(cfg.paths.archive_lock_file)
    try:
        lock.acquire()
    except AlreadyRunningError:
        logger.info("another archive process is running; exiting")
        return 0

    max_runtime = getattr(args, "max_runtime", None)
    if max_runtime:
        logger.info("archive max runtime %ss", max_runtime)
        install_max_runtime(max_runtime)

    proton_imap = None
    proton_password = None
    alert_event: AlertEvent | None = None
    try:
        hmac_key = get_generic_password(cfg.relay.hmac_keychain_service, "hmac").encode("utf-8")
        access_token = ""
        if not dry_run:
            if cfg.auth.method != "oauth2":
                raise ConfigError("archive --live requires auth.method = oauth2")
            store = OAuthTokenStore(cfg.auth.credentials_file, cfg.auth.token_file)
            access_token = store.get_access_token()
        proton_password = _proton_password(cfg, required=not dry_run)
        if proton_password and not dry_run:
            proton_imap = ProtonImap(cfg, proton_password, hmac_key=hmac_key)
            logger.info("connecting proton imap for archive")
            proton_imap.connect()
        ledger = Ledger(cfg.paths.ledger)
        result = process_archives(
            cfg,
            imap=proton_imap,
            hmac_key=hmac_key,
            dry_run=dry_run,
            ledger=ledger,
            access_token=access_token,
            force_key=getattr(args, "key", None) if getattr(args, "force", False) else None,
        )
        ledger.close()
        logger.info(
            "archive complete attempted=%s completed=%s temp=%s ops=%s unrecoverable=%s",
            result.attempted,
            result.completed,
            result.temporary_failures,
            result.operational_failures,
            result.unrecoverable,
        )
        for note in result.notes:
            print(note)
        if result.operational_failures:
            alert_event = AlertEvent("drive", "Drive auth or permission failure")
        return result.exit_code()
    except SystemExit:
        alert_event = AlertEvent("max_runtime", "max runtime exceeded")
        return 1
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except KeychainError as exc:
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 2
    except RelayError as exc:
        logger.error("archive failed: %s", exc)
        print(str(exc), file=sys.stderr)
        alert_event = classify_exception(exc)
        return 1
    finally:
        clear_max_runtime()
        if proton_imap is not None:
            try:
                proton_imap.close()
            except Exception:
                pass
        lock.release()
        maybe_alert(cfg, alert_event, proton_password, skip=dry_run)


def _proton_password(cfg, *, required: bool) -> str | None:
    import os

    env = os.environ.get("RESEARCH_RELAY_PROTON_PASSWORD", "").strip()
    if env:
        return env
    try:
        return get_generic_password(cfg.proton.keychain_service, cfg.proton.username)
    except KeychainError:
        if required:
            raise
        return None


def _gmail_auth(cfg):
    if cfg.auth.method == "oauth2":
        return build_auth(
            "oauth2",
            username=cfg.gmail.username,
            credentials_file=cfg.auth.credentials_file,
            token_file=cfg.auth.token_file,
        )
    password = get_generic_password(cfg.gmail.keychain_service, cfg.gmail.username)
    return build_auth("app_password", username=cfg.gmail.username, password=password)


def _want_dry_run(args: argparse.Namespace, cfg) -> bool:
    if args.dry_run:
        return True
    if args.live:
        if not cfg.relay.live_delivery:
            raise ConfigError("--live requires live_delivery = true in the config file")
        return False
    return True


def _resolve_config(explicit: str | None) -> Path:
    import os

    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("RESEARCH_RELAY_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path("~/.config/research-relay/config.toml").expanduser()


if __name__ == "__main__":
    raise SystemExit(main())
