from __future__ import annotations

import imaplib
import logging
import re
from typing import Iterable

from research_relay.age import gmail_pending_query
from research_relay.auth import GmailAuth
from research_relay.config import AppConfig
from research_relay.exceptions import TemporaryRelayError
from research_relay.imap_timeout import close_imap, enforce_socket_timeout, imap_timeout

log = logging.getLogger("research_relay")

_MSGID_RE = re.compile(rb"X-GM-MSGID\s+(\d+)")
_UID_MSGID_RE = re.compile(
    rb"UID\s+(\d+)(?:(?!UID\s).)*?X-GM-MSGID\s+(\d+)|X-GM-MSGID\s+(\d+)(?:(?!X-GM-MSGID\s).)*?UID\s+(\d+)",
    re.DOTALL,
)
_FETCH_CHUNK = 100


class GmailImap:
    def __init__(self, cfg: AppConfig, auth: GmailAuth) -> None:
        self._cfg = cfg
        self._auth = auth
        self._imap: imaplib.IMAP4_SSL | None = None
        self._folder = cfg.gmail.all_mail_folder
        self._uids: dict[str, str] = {}
        self._bodies: dict[str, bytes] = {}

    def connect(self) -> None:
        try:
            self._imap = imaplib.IMAP4_SSL(
                self._cfg.gmail.imap_host,
                self._cfg.gmail.imap_port,
                timeout=self._cfg.gmail.timeout_seconds,
            )
            enforce_socket_timeout(self._imap, self._cfg.gmail.timeout_seconds)
            log.info("gmail socket open; authenticating")
            self._auth.authenticate_imap(self._imap)
            enforce_socket_timeout(self._imap, self._cfg.gmail.timeout_seconds)
            log.info("gmail selecting folder=%s", self._folder)
            self._select()
            log.info("gmail imap connected folder=%s", self._folder)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"IMAP connect failed: {exc.__class__.__name__}") from exc

    def close(self) -> None:
        close_imap(self._imap)
        self._imap = None

    def search(self, query: str) -> list[str]:
        imap = self._require()
        quoted = '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"'
        try:
            typ, data = imap.uid("SEARCH", "X-GM-RAW", quoted)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"IMAP search failed: {exc.__class__.__name__}") from exc
        if typ != "OK":
            raise TemporaryRelayError("IMAP search returned a non-OK response")
        payload = data[0] if data else b""
        if not payload:
            return []
        return payload.decode("ascii", errors="ignore").split()

    def search_pending(self, limit: int | None = None) -> list[str]:
        relay = getattr(self._cfg, "relay", None)
        max_age_days = int(getattr(relay, "max_age_days", 0) or 0)
        query = gmail_pending_query(self._cfg.gmail.search_query, max_age_days)
        log.info("gmail searching pending query=%s", query)
        uids = self.search(query)
        log.info("gmail pending uids=%s", len(uids))
        if limit is not None:
            uids = uids[: max(0, int(limit))]
        if not uids:
            return []
        try:
            msgids = self._fetch_msgids(uids)
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"IMAP fetch failed: {exc.__class__.__name__}") from exc
        log.info("gmail pending messages=%s", len(msgids))
        return msgids

    def fetch_message(self, gmail_msgid: str) -> bytes:
        if gmail_msgid in self._bodies:
            return self._bodies[gmail_msgid]
        uid = self._uids.get(gmail_msgid)
        if uid is None:
            raise TemporaryRelayError("unknown Gmail message id for fetch")
        imap = self._require()
        try:
            typ, data = imap.uid("FETCH", uid, "(X-GM-MSGID X-GM-LABELS BODY.PEEK[])")
        except TimeoutError as exc:
            raise imap_timeout(exc) from exc
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"IMAP fetch failed: {exc.__class__.__name__}") from exc
        if typ != "OK":
            raise TemporaryRelayError("IMAP fetch returned a non-OK response")
        msgid, raw = _parse_fetch(data)
        if msgid:
            self._uids[msgid] = uid
        self._bodies[gmail_msgid] = raw
        return raw

    def apply_sent(self, gmail_msgid: str) -> None:
        self._store_labels(
            gmail_msgid,
            add=self._cfg.gmail.label_sent,
            remove=self._cfg.gmail.label_pending,
        )

    def apply_error(self, gmail_msgid: str) -> None:
        self._store_labels(
            gmail_msgid,
            add=self._cfg.gmail.label_error,
            remove=self._cfg.gmail.label_pending,
        )

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

    def _fetch_msgids(self, uids: list[str]) -> list[str]:
        imap = self._require()
        ordered: list[str] = []
        for start in range(0, len(uids), _FETCH_CHUNK):
            chunk = uids[start : start + _FETCH_CHUNK]
            log.info(
                "gmail fetching ids %s-%s/%s",
                start + 1,
                start + len(chunk),
                len(uids),
            )
            typ, data = imap.uid("FETCH", ",".join(chunk), "(UID X-GM-MSGID)")
            if typ != "OK":
                raise TemporaryRelayError("IMAP fetch returned a non-OK response")
            pairs = _parse_uid_msgids(data)
            by_uid = {uid: msgid for uid, msgid in pairs if uid}
            if by_uid:
                for uid in chunk:
                    msgid = by_uid.get(uid)
                    if not msgid:
                        continue
                    self._uids[msgid] = uid
                    ordered.append(msgid)
            else:
                for uid, (_ignored, msgid) in zip(chunk, pairs):
                    if not msgid:
                        continue
                    self._uids[msgid] = uid
                    ordered.append(msgid)
        return ordered

    def _store_labels(self, gmail_msgid: str, *, add: str, remove: str) -> None:
        uid = self._uids.get(gmail_msgid)
        if uid is None:
            raise TemporaryRelayError("unknown Gmail message id for label update")
        imap = self._require()
        try:
            typ, _ = imap.uid("STORE", uid, "+X-GM-LABELS", _label_atom(add))
            if typ != "OK":
                raise TemporaryRelayError("failed to add Gmail label")
            typ, _ = imap.uid("STORE", uid, "-X-GM-LABELS", _label_atom(remove))
            if typ != "OK":
                raise TemporaryRelayError("failed to remove Gmail label")
        except (OSError, imaplib.IMAP4.error) as exc:
            raise TemporaryRelayError(f"IMAP STORE failed: {exc.__class__.__name__}") from exc

    def _select(self) -> None:
        imap = self._require()
        folder = self._folder
        quoted = folder if folder.startswith('"') else f'"{folder}"'
        typ, _ = imap.select(quoted, readonly=False)
        if typ == "OK":
            return
        fallback = _find_all_mail(imap)
        if fallback:
            self._folder = fallback
            quoted = fallback if fallback.startswith('"') else f'"{fallback}"'
            typ, _ = imap.select(quoted, readonly=False)
            if typ == "OK":
                return
        raise TemporaryRelayError("unable to select Gmail All Mail")

    def _require(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            raise TemporaryRelayError("IMAP client is not connected")
        return self._imap


def _label_atom(label: str) -> str:
    escaped = label.replace("\\", "\\\\").replace('"', '\\"')
    return f'("{escaped}")'


def _parse_uid_msgids(data: Iterable[object]) -> list[tuple[str, str]]:
    meta = b""
    for item in data or []:
        if isinstance(item, tuple) and item:
            header = item[0]
            meta += b" "
            meta += header if isinstance(header, bytes) else str(header).encode("utf-8", errors="replace")
        elif isinstance(item, bytes):
            meta += b" "
            meta += item
        elif item:
            meta += b" "
            meta += str(item).encode("utf-8", errors="replace")
    pairs: list[tuple[str, str]] = []
    for match in _UID_MSGID_RE.finditer(meta):
        if match.group(1) is not None:
            pairs.append((match.group(1).decode("ascii"), match.group(2).decode("ascii")))
        else:
            pairs.append((match.group(4).decode("ascii"), match.group(3).decode("ascii")))
    if pairs:
        return pairs
    for match in _MSGID_RE.finditer(meta):
        pairs.append(("", match.group(1).decode("ascii")))
    return pairs


def _parse_fetch(data: Iterable[object]) -> tuple[str, bytes]:
    meta = b""
    raw = b""
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            header = item[0] if isinstance(item[0], bytes) else str(item[0]).encode("utf-8", errors="replace")
            body = item[1] if isinstance(item[1], bytes) else str(item[1]).encode("utf-8", errors="replace")
            meta += header
            raw = body
        elif isinstance(item, bytes):
            meta += item
        elif item:
            meta += str(item).encode("utf-8", errors="replace")
    match = _MSGID_RE.search(meta)
    msgid = match.group(1).decode("ascii") if match else ""
    return msgid, raw


def _find_all_mail(imap: imaplib.IMAP4) -> str | None:
    typ, data = imap.list()
    if typ != "OK" or not data:
        return None
    for item in data:
        if not item:
            continue
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        if "\\All" in text or "[Gmail]/All Mail" in text:
            match = re.search(r'"([^"]+)"\s*$', text)
            if match:
                return match.group(1)
    return None
