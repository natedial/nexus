#!/usr/bin/env python3
"""Read-only Proton Bridge IMAP probe for approach-1 viability.

Uses the same Bridge username, Keychain password, host, and CA as SMTP.
Does not change folders, flags, or read/unread state (BODY.PEEK + SELECT readonly).

Examples:
  python3 scripts/proton_imap_probe.py
  python3 scripts/proton_imap_probe.py --folder INBOX --max 15
  python3 scripts/proton_imap_probe.py --folder "Labels/Relay/pending"
"""

from __future__ import annotations

import argparse
import getpass
import imaplib
import re
import ssl
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_relay.cli import _resolve_config
from research_relay.config import load_config
from research_relay.exceptions import ConfigError, KeychainError
from research_relay.keychain import get_generic_password
from research_relay.proton_smtp import build_ssl_context

_GOOGLE_HINT = re.compile(
    rb"(mx\.google\.com|mail-[\w.-]*\.google\.com|x-google-|x-gm-|google\.com\b)",
    re.IGNORECASE,
)
_MAILBOX_RE = re.compile(r'"((?:\\.|[^"\\])*)"\s*$')


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    try:
        cfg = load_config(_resolve_config(args.config))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    host = args.imap_host or cfg.proton.smtp_host
    port = args.imap_port
    folder = args.folder
    try:
        context = build_ssl_context(cfg.proton)
        if args.prompt:
            password = getpass.getpass("Proton Bridge IMAP/SMTP password: ")
            if not password:
                print("no password entered", file=sys.stderr)
                return 2
        else:
            password = get_generic_password(cfg.proton.keychain_service, cfg.proton.username)
    except (ConfigError, KeychainError) as exc:
        print(str(exc), file=sys.stderr)
        if not args.prompt:
            print("Retry with --prompt to type the Bridge password instead of using Keychain.", file=sys.stderr)
        return 2

    imap = None
    try:
        imap = _connect(host, port, cfg.proton.username, password, context, cfg.proton.timeout_seconds)
    except ProbeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        caps = sorted(_capabilities(imap))
        print(f"account: {cfg.proton.username}")
        print(f"imap:    {host}:{port} STARTTLS")
        print(f"folder:  {folder}")
        print(f"x-gm-ext-1: {'yes' if 'X-GM-EXT-1' in caps else 'no'}")
        print(f"caps:    {', '.join(caps) or '(none)'}")
        print()

        print("folders:")
        names = _list_folders(imap)
        if not names:
            print("  (none listed)")
        for name in names:
            marker = "  <- selected" if _norm(name) == _norm(folder) else ""
            print(f"  {name}{marker}")
        print()

        uidvalidity, uids = _select_recent(imap, folder, args.max)
        print(f"uidvalidity: {uidvalidity or '?'}")
        print(f"messages:    {len(uids)} (most recent in {folder!r})")
        print()
        if not uids:
            print("No messages in that folder.")
            print("If the Proton-only mail is in Inbox, this login/fetch path still works.")
            return 0

        with_msgid = 0
        with_google = 0
        with_body = 0
        for index, uid in enumerate(uids, start=1):
            header_raw, text_raw = _peek(imap, uid)
            parsed = BytesParser(policy=policy.default).parsebytes(header_raw or b"")
            message_id = str(parsed.get("Message-ID") or "").strip()
            google = bool(_GOOGLE_HINT.search(header_raw or b""))
            if message_id:
                with_msgid += 1
            if google:
                with_google += 1
            if text_raw:
                with_body += 1
            print(f"{index}. {parsed.get('Subject') or '(no subject)'}")
            print(f"   From:       {parsed.get('From') or '?'}")
            print(f"   Date:       {parsed.get('Date') or '?'}")
            print(f"   Message-ID: {message_id or '(none)'}")
            print(f"   google hops:{' yes' if google else ' no'}")
            print(f"   body peek:  {len(text_raw)} bytes")
            print(f"   uid:        {uid}")
            print()

        print("viability:")
        print(f"  login+peek:     ok")
        print(f"  Message-ID:     {with_msgid}/{len(uids)} messages")
        print(f"  google hops:    {with_google}/{len(uids)} messages")
        print(f"  decrypted body: {with_body}/{len(uids)} messages")
        print(f"  X-GM-EXT-1:     {'present (label STORE may work)' if 'X-GM-EXT-1' in caps else 'absent (use COPY into a Labels/ folder)'}")
        return 0
    except ProbeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--config",
        default=None,
        help="TOML config (default: $RESEARCH_RELAY_CONFIG or ~/.config/research-relay/config.toml)",
    )
    parser.add_argument("--imap-host", default=None, help="Override IMAP host (default: proton.smtp_host)")
    parser.add_argument("--imap-port", type=int, default=1143, help="Bridge IMAP port (default 1143)")
    parser.add_argument("--folder", default="INBOX", help="IMAP folder to peek (default INBOX)")
    parser.add_argument("--max", type=int, default=10, help="Max recent messages to print (default 10)")
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Ask for the Bridge password instead of reading Keychain (workaround for macOS 26 security -w)",
    )
    return parser.parse_args(argv)


def _connect(
    host: str,
    port: int,
    username: str,
    password: str,
    context: ssl.SSLContext,
    timeout: float,
) -> imaplib.IMAP4:
    try:
        imap = imaplib.IMAP4(host, port, timeout=timeout)
        imap.starttls(ssl_context=context)
        imap.login(username, password)
    except ConnectionRefusedError as exc:
        raise ProbeError(
            f"Bridge IMAP refused {host}:{port}. Is Proton Mail Bridge running?"
        ) from exc
    except ssl.SSLError as exc:
        raise ProbeError(
            f"Bridge IMAP TLS failed ({exc.__class__.__name__}). Check proton.ca_file / allow_insecure_tls."
        ) from exc
    except imaplib.IMAP4.error as exc:
        raise ProbeError(f"Bridge IMAP login failed: {exc}") from exc
    except (OSError, TimeoutError) as exc:
        raise ProbeError(f"Bridge IMAP connect failed: {exc.__class__.__name__}") from exc
    return imap


def _capabilities(imap: imaplib.IMAP4) -> set[str]:
    parts: list[str] = []
    try:
        typ, data = imap.capability()
    except imaplib.IMAP4.error:
        typ, data = "NO", []
    blobs = data if typ == "OK" else list(imap.capabilities or ())
    for item in blobs:
        if isinstance(item, bytes):
            text = item.decode("ascii", errors="ignore")
        else:
            text = str(item)
        parts.extend(text.upper().split())
    return {part for part in parts if part and part != "CAPABILITY"}


def _list_folders(imap: imaplib.IMAP4) -> list[str]:
    typ, data = imap.list()
    if typ != "OK" or not data:
        return []
    names: list[str] = []
    for item in data:
        if not item:
            continue
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        match = _MAILBOX_RE.search(text)
        names.append(match.group(1).replace('\\"', '"') if match else text)
    return names


def _select_recent(imap: imaplib.IMAP4, folder: str, limit: int) -> tuple[str, list[str]]:
    quoted = _quote_mailbox(folder)
    typ, data = imap.select(quoted, readonly=True)
    if typ != "OK":
        raise ProbeError(f"could not select folder {folder!r} (try a name from the folder list)")
    uidvalidity = ""
    try:
        status_typ, status_data = imap.status(quoted, "(UIDVALIDITY)")
        if status_typ == "OK" and status_data and status_data[0]:
            blob = status_data[0] if isinstance(status_data[0], bytes) else str(status_data[0]).encode()
            match = re.search(rb"UIDVALIDITY\s+(\d+)", blob, re.IGNORECASE)
            if match:
                uidvalidity = match.group(1).decode("ascii")
    except imaplib.IMAP4.error:
        pass
    typ, data = imap.uid("SEARCH", None, "ALL")
    if typ != "OK":
        raise ProbeError(f"IMAP SEARCH failed in {folder!r}")
    payload = data[0] if data else b""
    if not payload:
        return uidvalidity, []
    uids = payload.decode("ascii", errors="ignore").split()
    if limit > 0:
        uids = uids[-limit:]
    return uidvalidity, uids


def _peek(imap: imaplib.IMAP4, uid: str) -> tuple[bytes, bytes]:
    try:
        typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT])")
    except imaplib.IMAP4.error as exc:
        raise ProbeError(f"FETCH uid {uid} failed: {exc}") from exc
    if typ != "OK":
        raise ProbeError(f"FETCH uid {uid} returned {typ}")
    header = b""
    text = b""
    for item in data or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        meta = item[0] if isinstance(item[0], bytes) else str(item[0]).encode()
        body = item[1] if isinstance(item[1], bytes) else str(item[1]).encode()
        upper = meta.upper()
        if b"BODY[HEADER]" in upper or b"BODY.PEEK[HEADER]" in upper:
            header = body
        elif b"BODY[TEXT]" in upper or b"BODY.PEEK[TEXT]" in upper:
            text = body
        elif not header:
            header = body
    return header, text


def _quote_mailbox(folder: str) -> str:
    text = folder.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _norm(name: str) -> str:
    return name.strip().strip('"').lower()


class ProbeError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
