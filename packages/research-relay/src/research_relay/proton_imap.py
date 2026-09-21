from __future__ import annotations

import imaplib
import logging
import re
import socket
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser

from research_relay.age import header_is_fresh, header_is_on_or_after, imap_since_date
from research_relay.config import AppConfig
from research_relay.domain import address_is_one_of, message_id_from_domain
from research_relay.exceptions import TemporaryRelayError
from research_relay.google_hops import has_google_hops
from research_relay.imap_timeout import close_imap, enforce_socket_timeout, imap_timeout
from research_relay.proton_smtp import build_ssl_context
from research_relay.stamp import raw_is_own_output

log = logging.getLogger("research_relay")

_MSGID_RE = re.compile(rb"(?im)^Message-ID:\s*(.+)$")
_DISMISS_CHUNK = 50
_RECENT_SCAN_CAP = 5000


def quote_mailbox(folder: str) -> str:
    text = folder.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def ledger_key_for_message_id(message_id: str, uid: str) -> str:
    text = (message_id or "").strip()
    if text:
        return f"proton:{text}"
    return f"proton:uid-{uid}"


class ProtonImap:
    def __init__(self, cfg: AppConfig, password: str, hmac_key: bytes = b"") -> None:
        self._cfg = cfg
        self._password = password
        self._hmac_key = hmac_key
        self._imap: imaplib.IMAP4 | None = None
        self._uids: dict[str, str] = {}
        self._bodies: dict[str, bytes] = {}
        self._gmail_copies: list[str] = []

    def connect(self) -> None:
        proton = self._cfg.proton
        timeout = max(1.0, float(proton.timeout_seconds))
        previous_default = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout)
            imap = imaplib.IMAP4(proton.imap_host, proton.imap_port, timeout=timeout)
            enforce_socket_timeout(imap, timeout)
            imap.starttls(ssl_context=build_ssl_context(proton))
            enforce_socket_timeout(imap, timeout)
            imap.login(proton.username, self._password)
            enforce_socket_timeout(imap, timeout)
            self._imap = imap
            self._select(proton.folder_pending)
            log.info("proton imap connected folder=%s", proton.folder_pending)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            self._imap = None
            raise TemporaryRelayError(f"Proton IMAP connect failed: {exc.__class__.__name__}: {exc}") from exc
        finally:
            socket.setdefaulttimeout(previous_default)

    def close(self) -> None:
        close_imap(self._imap)
        self._imap = None

    def count_pending(self) -> int:
        self._select(self._cfg.proton.folder_pending)
        uids = self._search_all_uids()
        log.info("proton pending uids=%s", len(uids))
        return len(uids)

    def search_pending(self, limit: int | None = None) -> list[str]:
        self._select(self._cfg.proton.folder_pending)
        self._gmail_copies = []
        self._uids = {}
        log.info("proton searching pending")
        uids = self._search_all_uids()
        if not uids:
            log.info("proton pending uids=0")
            return []
        log.info("proton pending uids=%s", len(uids))
        native: list[str] = []
        stale = 0
        relay = getattr(self._cfg, "relay", None)
        max_age_days = int(getattr(relay, "max_age_days", 0) or 0)
        try:
            for index, uid in enumerate(uids, start=1):
                header = self._fetch_header(uid)
                key = ledger_key_for_message_id(_message_id(header), uid)
                self._uids[key] = uid
                if has_google_hops(header) or self._is_own_relay(uid, header):
                    self._gmail_copies.append(key)
                elif header_is_fresh(header, max_age_days):
                    native.append(key)
                else:
                    stale += 1
                hit_limit = limit is not None and len(native) >= max(0, int(limit))
                if index == 1 or index % 25 == 0 or index == len(uids) or hit_limit:
                    log.info(
                        "proton classifying %s/%s native=%s gmail_copies=%s stale=%s",
                        index,
                        len(uids),
                        len(native),
                        len(self._gmail_copies),
                        stale,
                    )
                if hit_limit:
                    break
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        log.info("proton pending messages=%s", len(native))
        return native

    def dismiss_gmail_copies(self, *, dry_run: bool = False) -> int:
        copies = list(self._gmail_copies)
        if not copies:
            return 0
        if dry_run:
            log.info("proton would dismiss gmail copies=%s", len(copies))
            return len(copies)
        uids = [self._uids[key] for key in copies if key in self._uids]
        log.info("proton dismissing gmail copies=%s", len(uids))
        if not uids:
            self._gmail_copies = []
            return len(copies)
        imap = self._require()
        self._select(self._cfg.proton.folder_pending)
        dest = quote_mailbox(self._cfg.proton.folder_inbox)
        try:
            for start in range(0, len(uids), _DISMISS_CHUNK):
                chunk = uids[start : start + _DISMISS_CHUNK]
                typ, _ = imap.uid("MOVE", ",".join(chunk), dest)
                if typ != "OK":
                    raise TemporaryRelayError("failed to dismiss Proton Gmail copy")
                log.info(
                    "proton dismissed copies %s-%s/%s",
                    start + 1,
                    start + len(chunk),
                    len(uids),
                )
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP MOVE failed: {exc.__class__.__name__}") from exc
        self._gmail_copies = []
        return len(copies)

    def fetch_by_message_id(self, message_id: str) -> bytes:
        text = (message_id or "").strip()
        if not text:
            raise TemporaryRelayError("missing Proton Message-ID for archive fetch")
        variants = [text]
        if text.startswith("<") and text.endswith(">"):
            variants.append(text[1:-1])
        else:
            variants.append(f"<{text}>")
        imap = self._require()
        folders = (
            self._cfg.proton.folder_sent,
            self._cfg.proton.folder_inbox,
            self._cfg.proton.folder_pending,
        )
        try:
            for folder in folders:
                self._select(folder)
                for variant in variants:
                    typ, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", variant)
                    if typ != "OK":
                        continue
                    payload = data[0] if data else b""
                    uids = payload.decode("ascii", errors="ignore").split() if payload else []
                    if not uids:
                        continue
                    uid = uids[0]
                    typ, fetched = imap.uid("FETCH", uid, "(BODY.PEEK[])")
                    if typ != "OK":
                        raise TemporaryRelayError("Proton IMAP fetch returned a non-OK response")
                    raw = _fetch_body(fetched)
                    if raw:
                        return raw
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(
                f"Proton IMAP archive fetch failed: {exc.__class__.__name__}: {exc}"
            ) from exc
        raise TemporaryRelayError("proton message not found for archive")

    def collect_recent_native(
        self,
        *,
        hours: int | None = None,
        since: datetime | None = None,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if since is not None:
            cutoff = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        else:
            cutoff = moment - timedelta(hours=max(1, int(hours or 48)))
        folders = (
            self._cfg.proton.folder_sent,
            self._cfg.proton.folder_pending,
        )
        found: list[str] = []
        self._uids = {}
        self._bodies = {}
        cap = _RECENT_SCAN_CAP if limit is None else min(_RECENT_SCAN_CAP, max(0, int(limit)))
        try:
            for folder in folders:
                self._select(folder)
                uids = self._search_since(cutoff)
                log.info(
                    "proton recent folder=%s uids=%s since=%s",
                    folder,
                    len(uids),
                    imap_since_date(cutoff),
                )
                for uid in uids:
                    header = self._fetch_header(uid)
                    key = ledger_key_for_message_id(_message_id(header), uid)
                    if key in found:
                        continue
                    if has_google_hops(header) or self._is_own_relay(uid, header):
                        continue
                    if not header_is_on_or_after(header, cutoff):
                        continue
                    raw = self._fetch_full(uid)
                    if not raw:
                        continue
                    self._uids[key] = uid
                    self._bodies[key] = raw
                    found.append(key)
                    if cap and len(found) >= cap:
                        log.info("proton recent native=%s (cap)", len(found))
                        return found
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(
                f"Proton IMAP recent search failed: {exc.__class__.__name__}: {exc}"
            ) from exc
        log.info("proton recent native=%s", len(found))
        return found

    def fetch_message(self, gmail_msgid: str) -> bytes:
        if gmail_msgid in self._bodies:
            return self._bodies[gmail_msgid]
        uid = self._uids.get(gmail_msgid)
        if uid is None:
            raise TemporaryRelayError("unknown Proton message id for fetch")
        imap = self._require()
        self._select(self._cfg.proton.folder_pending)
        try:
            typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP fetch failed: {exc.__class__.__name__}") from exc
        if typ != "OK":
            raise TemporaryRelayError("Proton IMAP fetch returned a non-OK response")
        raw = _fetch_body(data)
        self._bodies[gmail_msgid] = raw
        return raw

    def apply_sent(self, gmail_msgid: str) -> None:
        self._move_pending_to(gmail_msgid, self._cfg.proton.folder_sent)

    def apply_error(self, gmail_msgid: str) -> None:
        self._move_pending_to(gmail_msgid, self._cfg.proton.folder_error)

    def list_mailbox_names(self) -> list[str]:
        imap = self._require()
        typ, data = imap.list()
        if typ != "OK" or not data:
            return []
        names: list[str] = []
        for item in data:
            if not item:
                continue
            text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
            names.append(text)
        return names

    def noop(self) -> None:
        self._require().noop()

    def _move_pending_to(self, key: str, dest_folder: str) -> None:
        """Move a pending message onto another Proton *label* folder.

        Bridge treats labels as IMAP folders. COPY into a label adds it;
        MOVE from one label to another adds the destination and removes the
        source. COPY-then-MOVE-to-INBOX was returning OK while Relay/pending
        stayed put, so we MOVE pending → sent/error and verify both sides.
        """
        message_id = _rfc822_id_from_key(key)
        uid = self._resolve_pending_uid(key, message_id)
        imap = self._require()
        self._select(self._cfg.proton.folder_pending)
        try:
            typ, _ = imap.uid("MOVE", uid, quote_mailbox(dest_folder))
            if typ != "OK":
                raise TemporaryRelayError(f"failed to move Proton message to {dest_folder}")
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP MOVE failed: {exc.__class__.__name__}") from exc
        self._uids.pop(key, None)
        if message_id and self._uids_for_message_id(self._cfg.proton.folder_pending, message_id):
            raise TemporaryRelayError("Proton pending label still present after MOVE")
        if message_id and not self._uids_for_message_id(dest_folder, message_id):
            raise TemporaryRelayError(f"Proton message missing from {dest_folder} after MOVE")
        # Verification SELECTs dest_folder. Later fetches must run against pending.
        self._select(self._cfg.proton.folder_pending)

    def _resolve_pending_uid(self, key: str, message_id: str) -> str:
        uid = self._uids.get(key)
        if uid:
            return uid
        if message_id:
            found = self._uids_for_message_id(self._cfg.proton.folder_pending, message_id)
            if found:
                self._uids[key] = found[0]
                return found[0]
        raise TemporaryRelayError("unknown Proton message id for label update")

    def _uids_for_message_id(self, folder: str, message_id: str) -> list[str]:
        text = (message_id or "").strip()
        if not text:
            return []
        variants = [text]
        if text.startswith("<") and text.endswith(">"):
            variants.append(text[1:-1])
        else:
            variants.append(f"<{text}>")
        imap = self._require()
        self._select(folder)
        found: list[str] = []
        try:
            for variant in variants:
                typ, data = imap.uid("SEARCH", None, "HEADER", "Message-ID", variant)
                if typ != "OK":
                    continue
                payload = data[0] if data else b""
                uids = payload.decode("ascii", errors="ignore").split() if payload else []
                for uid in uids:
                    if uid not in found:
                        found.append(uid)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP search failed: {exc.__class__.__name__}") from exc
        return found

    def _move_to_inbox(self, key: str) -> None:
        uid = self._uids.get(key)
        if uid is None:
            return
        imap = self._require()
        self._select(self._cfg.proton.folder_pending)
        try:
            typ, _ = imap.uid("MOVE", uid, quote_mailbox(self._cfg.proton.folder_inbox))
            if typ != "OK":
                raise TemporaryRelayError("failed to dismiss Proton Gmail copy")
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP MOVE failed: {exc.__class__.__name__}") from exc

    def _search_all_uids(self) -> list[str]:
        return self._search_uids("ALL")

    def _search_since(self, since: datetime) -> list[str]:
        return self._search_uids("SINCE", imap_since_date(since))

    def _search_uids(self, *criteria: str) -> list[str]:
        imap = self._require()
        try:
            typ, data = imap.uid("SEARCH", None, *criteria)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"Proton IMAP search failed: {exc.__class__.__name__}") from exc
        if typ != "OK":
            raise TemporaryRelayError("Proton IMAP search returned a non-OK response")
        payload = data[0] if data else b""
        if not payload:
            return []
        return payload.decode("ascii", errors="ignore").split()

    def _fetch_full(self, uid: str) -> bytes:
        imap = self._require()
        typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK":
            return b""
        return _fetch_body(data)

    def _is_own_relay(self, uid: str, header: bytes) -> bool:
        if _header_is_own_relay(self._cfg, header):
            return True
        if raw_is_own_output(header, self._hmac_key):
            return True
        if not self._hmac_key:
            return False
        return raw_is_own_output(b"", self._hmac_key, self._fetch_text_prefix(uid))

    def _fetch_text_prefix(self, uid: str) -> bytes:
        imap = self._require()
        typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[TEXT]<0.2048>)")
        if typ != "OK":
            return b""
        return _fetch_body(data)

    def _fetch_header(self, uid: str) -> bytes:
        imap = self._require()
        typ, data = imap.uid("FETCH", uid, "(BODY.PEEK[HEADER])")
        if typ != "OK":
            return b""
        return _fetch_body(data)

    def _select(self, folder: str) -> None:
        imap = self._require()
        quoted = quote_mailbox(folder)
        typ, _ = imap.select(quoted, readonly=False)
        if typ != "OK":
            raise TemporaryRelayError(f"unable to select Proton folder {folder}")

    def _require(self) -> imaplib.IMAP4:
        if self._imap is None:
            raise TemporaryRelayError("Proton IMAP client is not connected")
        return self._imap


def _header_is_own_relay(cfg: object, header: bytes) -> bool:
    parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
    proton = getattr(cfg, "proton", None)
    if address_is_one_of(
        str(parsed.get("From") or ""),
        [
            getattr(proton, "from_address", ""),
            getattr(proton, "reply_to", ""),
        ],
    ):
        return True
    relay = getattr(cfg, "relay", None)
    mid = str(parsed.get("Message-ID") or "").strip() or _message_id(header)
    return message_id_from_domain(mid, str(getattr(relay, "message_id_domain", "") or ""))


def _rfc822_id_from_key(key: str) -> str:
    text = (key or "").strip()
    if text.startswith("proton:"):
        text = text[7:]
    if not text or text.startswith("uid-"):
        return ""
    return text


def _message_id(header: bytes) -> str:
    match = _MSGID_RE.search(header.replace(b"\r\n", b"\n"))
    if not match:
        parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
        return str(parsed.get("Message-ID") or "").strip()
    return match.group(1).decode("utf-8", errors="replace").strip()


def _fetch_body(data) -> bytes:
    raw = b""
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            body = item[1]
            raw = body if isinstance(body, bytes) else str(body).encode("utf-8", errors="replace")
        elif isinstance(item, bytes) and not raw:
            raw = item
    return raw
