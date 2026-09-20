"""IMAP/SMTP client unit tests with protocol stubs."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from research_relay.gmail_imap import GmailImap
from research_relay.proton_imap import ProtonImap, ledger_key_for_message_id, quote_mailbox
from research_relay.proton_smtp import ProtonSmtp


class ScriptedImap:
    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.selected = None
        self.timeout = None

    def login(self, user: str, password: str) -> tuple[str, list]:
        self.commands.append(("login", user))
        return "OK", [b"Logged in"]

    def list(self, *args) -> tuple[str, list]:
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"']

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list]:
        self.selected = mailbox
        self.commands.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command: str, *args) -> tuple[str, list]:
        self.commands.append(("uid", command, args))
        if command.upper() == "SEARCH":
            return "OK", [getattr(self, "search_uids", b"1 2")]
        if command.upper() == "FETCH":
            uid_arg = str(args[0]) if args else ""
            spec = str(args[1]).upper() if len(args) > 1 else ""
            if "BODY" in spec:
                return "OK", [(b"1 (X-GM-MSGID 99 X-GM-LABELS (Relay/pending) BODY[] {8}", b"From: x\n\nhi")]
            items = []
            for uid in uid_arg.split(","):
                uid = uid.strip()
                if not uid:
                    continue
                items.append(f"{uid} (UID {uid} X-GM-MSGID {9000 + int(uid)})".encode("ascii"))
            return "OK", items
        if command.upper() == "STORE":
            return "OK", [b""]
        return "OK", [b""]

    def logout(self) -> tuple[str, list]:
        return "BYE", []

    def noop(self) -> tuple[str, list]:
        return "OK", []


def test_gmail_search_uses_gm_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = ScriptedImap()
    client = GmailImap.__new__(GmailImap)
    client._imap = scripted
    client._folder = "[Gmail]/All Mail"
    uids = client.search('label:relay/pending -label:relay/sent -in:spam -in:trash')
    uid_cmds = [c for c in scripted.commands if c[0] == "uid"]
    assert uid_cmds
    assert "X-GM-RAW" in str(uid_cmds[0])


def test_gmail_search_pending_batches_limited_uids() -> None:
    from types import SimpleNamespace

    scripted = ScriptedImap()
    scripted.search_uids = b"1 2 3 4 5"
    client = GmailImap.__new__(GmailImap)
    client._imap = scripted
    client._folder = "[Gmail]/All Mail"
    client._uids = {}
    client._bodies = {}
    client._cfg = SimpleNamespace(gmail=SimpleNamespace(search_query="label:relay/pending"))
    pending = client.search_pending(limit=3)
    assert pending == ["9001", "9002", "9003"]
    fetch_cmds = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "FETCH"]
    assert len(fetch_cmds) == 1
    assert fetch_cmds[0][2][0] == "1,2,3"


def test_gmail_search_pending_applies_newer_than() -> None:
    from types import SimpleNamespace

    scripted = ScriptedImap()
    scripted.search_uids = b"1 2 3"
    client = GmailImap.__new__(GmailImap)
    client._imap = scripted
    client._folder = "[Gmail]/All Mail"
    client._uids = {}
    client._bodies = {}
    client._cfg = SimpleNamespace(
        gmail=SimpleNamespace(search_query="label:relay/pending"),
        relay=SimpleNamespace(max_age_days=5),
    )
    client.search_pending(limit=3)
    search_cmds = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "SEARCH"]
    assert search_cmds
    assert "newer_than:5d" in str(search_cmds[0])

class ScriptedSmtp:
    def __init__(self) -> None:
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        self.ehlo_called = False

    def ehlo(self) -> None:
        self.ehlo_called = True

    def starttls(self, context=None) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def sendmail(self, from_addr: str, to_addrs, msg: bytes) -> dict:
        self.sent = (from_addr, list(to_addrs), msg)
        return {}

    def mail(self, sender: str) -> None:
        return None

    def rcpt(self, recipient: str) -> None:
        return None

    def noop(self) -> tuple[int, bytes]:
        return 250, b"ok"

    def quit(self) -> None:
        return None


def test_proton_send_uses_envelope_recipients(monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = ScriptedSmtp()
    client = ProtonSmtp.__new__(ProtonSmtp)
    client._smtp = scripted
    client._from_address = "relay@proton.me"
    msg = EmailMessage()
    msg["From"] = "relay@proton.me"
    msg["To"] = "undisclosed-recipients:;"
    msg.set_content("hi")
    client.send(msg, envelope_recipients=["c1@proton.me", "c2@example.org"])
    assert scripted.sent[0] == "relay@proton.me"
    assert scripted.sent[1] == ["c1@proton.me", "c2@example.org"]
    assert b"Bcc:" not in scripted.sent[2]
    assert b"c1@proton.me" not in scripted.sent[2]


def test_quote_mailbox_escapes_backslash() -> None:
    assert quote_mailbox(r"Labels/Relay\/pending") == r'"Labels/Relay\\/pending"'


def test_ledger_key_uses_message_id() -> None:
    assert ledger_key_for_message_id("<abc@proton.me>", "12") == "proton:<abc@proton.me>"
    assert ledger_key_for_message_id("", "12") == "proton:uid-12"


class ScriptedProtonImap:
    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.selected = None
        self.headers = {
            "1": (
                b"From: Alice <alice@candidates.edu>\r\n"
                b"Message-ID: <native@proton.me>\r\n\r\n"
            ),
            "2": (
                b"From: Alice <alice@candidates.edu>\r\n"
                b"Message-ID: <copy@mail.gmail.com>\r\n"
                b"Received: from mx.google.com by mx.google.com\r\n\r\n"
            ),
        }
        self.bodies = {
            "1": (
                b"From: Alice <alice@candidates.edu>\r\n"
                b"Message-ID: <native@proton.me>\r\n\r\nhello\r\n"
            ),
        }
        pending = quote_mailbox(r"Labels/Relay\/pending")
        sent = quote_mailbox(r"Labels/Relay\/sent")
        error = quote_mailbox(r"Labels/Relay\/error")
        inbox = quote_mailbox("INBOX")
        self.mailboxes = {
            pending: ["1", "2"],
            sent: [],
            error: [],
            inbox: [],
        }

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list]:
        self.selected = mailbox
        self.commands.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command: str, *args) -> tuple[str, list]:
        self.commands.append(("uid", command, args))
        verb = command.upper()
        if verb == "SEARCH":
            override = getattr(self, "search_uids", None)
            if override is not None and not (
                "HEADER" in " ".join(str(a) for a in args).upper()
            ):
                return "OK", [override]
            uids = list(self.mailboxes.get(self.selected, []))
            joined = " ".join(str(a) for a in args).upper()
            if "HEADER" in joined and "MESSAGE-ID" in joined:
                needle = str(args[-1]).strip()
                matched = []
                for uid in uids:
                    header = self.headers.get(uid, b"")
                    if needle.encode("utf-8") in header or needle.strip("<>").encode("utf-8") in header:
                        matched.append(uid)
                payload = " ".join(matched).encode("ascii") if matched else b""
                return "OK", [payload]
            payload = " ".join(uids).encode("ascii") if uids else b""
            return "OK", [payload]
        if verb == "FETCH":
            uid = str(args[0])
            spec = str(args[1]).upper()
            selected_uids = self.mailboxes.get(self.selected, [])
            if uid not in selected_uids:
                return "OK", [(b"BODY[] {0}", b"")]
            if "HEADER" in spec:
                return "OK", [(b"BODY[HEADER] {1}", self.headers[uid])]
            return "OK", [(b"BODY[] {1}", self.bodies.get(uid, b"hello\r\n"))]
        if verb == "COPY":
            uid = str(args[0])
            dest = str(args[1])
            bucket = self.mailboxes.setdefault(dest, [])
            if uid not in bucket:
                bucket.append(uid)
            return "OK", [b""]
        if verb == "MOVE":
            uid = str(args[0])
            dest = str(args[1])
            current = self.mailboxes.get(self.selected, [])
            if uid in current:
                current.remove(uid)
            bucket = self.mailboxes.setdefault(dest, [])
            if uid not in bucket:
                bucket.append(uid)
            return "OK", [b""]
        return "OK", [b""]

    def list(self, *args) -> tuple[str, list]:
        return "OK", [b'(\\HasNoChildren) "/" "Labels/Relay/pending"']

    def noop(self) -> tuple[str, list]:
        return "OK", []

    def logout(self) -> tuple[str, list]:
        return "BYE", []


def _proton_client(scripted: ScriptedProtonImap) -> ProtonImap:
    from types import SimpleNamespace

    client = ProtonImap.__new__(ProtonImap)
    client._imap = scripted
    client._cfg = SimpleNamespace(
        proton=SimpleNamespace(
            folder_pending=r"Labels/Relay\/pending",
            folder_sent=r"Labels/Relay\/sent",
            folder_error=r"Labels/Relay\/error",
            folder_inbox="INBOX",
            from_address="relay@proton.me",
            reply_to="relay-reply@proton.me",
        ),
        relay=SimpleNamespace(max_age_days=0, message_id_domain="relay.local"),
    )
    client._uids = {}
    client._bodies = {}
    client._gmail_copies = []
    client._password = "x"
    client._hmac_key = b"k"
    return client


def test_proton_search_returns_native_and_records_gmail_copies() -> None:
    scripted = ScriptedProtonImap()
    client = _proton_client(scripted)
    pending = client.search_pending()
    assert pending == ["proton:<native@proton.me>"]
    assert client._gmail_copies == ["proton:<copy@mail.gmail.com>"]
    dismissed = client.dismiss_gmail_copies(dry_run=False)
    assert dismissed == 1
    move_cmds = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "MOVE"]
    assert move_cmds


def test_proton_fetch_after_apply_sent_selects_pending() -> None:
    scripted = ScriptedProtonImap()
    pending = quote_mailbox(r"Labels/Relay\/pending")
    scripted.headers["3"] = (
        b"From: Bob <bob@proton.me>\r\n"
        b"Message-ID: <native2@proton.me>\r\n\r\n"
    )
    scripted.bodies["3"] = (
        b"From: Bob <bob@proton.me>\r\n"
        b"Message-ID: <native2@proton.me>\r\n\r\nsecond\r\n"
    )
    scripted.mailboxes[pending].append("3")
    client = _proton_client(scripted)
    found = client.search_pending()
    assert "proton:<native2@proton.me>" in found
    client.apply_sent("proton:<native@proton.me>")
    raw = client.fetch_message("proton:<native2@proton.me>")
    assert b"From: Bob <bob@proton.me>" in raw
    assert scripted.selected == pending
    fetch_cmds = [
        c
        for c in scripted.commands
        if c[0] == "uid" and str(c[1]).upper() == "FETCH" and "HEADER" not in str(c[2][1]).upper()
    ]
    assert fetch_cmds
    selects_before_last_fetch = [
        c for c in scripted.commands[: scripted.commands.index(fetch_cmds[-1])] if c[0] == "select"
    ]
    assert selects_before_last_fetch[-1][1] == pending


def test_proton_apply_sent_moves_pending_to_sent() -> None:
    scripted = ScriptedProtonImap()
    client = _proton_client(scripted)
    client.search_pending()
    client.apply_sent("proton:<native@proton.me>")
    move_cmds = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "MOVE"]
    assert move_cmds
    assert move_cmds[-1][2][1] == quote_mailbox(r"Labels/Relay\/sent")
    copy_cmds = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "COPY"]
    assert copy_cmds == []
    pending = quote_mailbox(r"Labels/Relay\/pending")
    sent = quote_mailbox(r"Labels/Relay\/sent")
    assert "1" not in scripted.mailboxes[pending]
    assert "1" in scripted.mailboxes[sent]


def test_proton_apply_sent_fails_if_still_pending() -> None:
    from research_relay.exceptions import TemporaryRelayError

    class Sticky(ScriptedProtonImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            if str(command).upper() == "MOVE":
                self.commands.append(("uid", command, args))
                return "OK", [b""]
            return super().uid(command, *args)

    client = _proton_client(Sticky())
    client.search_pending()
    with pytest.raises(TemporaryRelayError, match="pending label still present"):
        client.apply_sent("proton:<native@proton.me>")


def test_proton_apply_sent_timeout_is_temporary() -> None:
    from research_relay.exceptions import TemporaryRelayError

    class Slow(ScriptedProtonImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            if str(command).upper() in {"COPY", "MOVE"}:
                raise TimeoutError("timed out")
            return super().uid(command, *args)

    client = _proton_client(Slow())
    client.search_pending()
    with pytest.raises(TemporaryRelayError, match="timed out"):
        client.apply_sent("proton:<native@proton.me>")


def test_proton_search_pending_stops_at_limit() -> None:
    scripted = ScriptedProtonImap()
    client = _proton_client(scripted)
    pending = client.search_pending(limit=1)
    assert pending == ["proton:<native@proton.me>"]
    assert client._gmail_copies == []
    header_fetches = [
        c
        for c in scripted.commands
        if c[0] == "uid" and str(c[1]).upper() == "FETCH" and "HEADER" in str(c[2][1]).upper()
    ]
    assert len(header_fetches) == 1


def test_proton_search_pending_dismisses_own_relay_output() -> None:
    scripted = ScriptedProtonImap()
    scripted.headers["1"] = (
        b"From: relay@proton.me\r\n"
        b"Date: Thu, 20 Aug 2026 21:55:06 +0000\r\n"
        b"Message-ID: <deadbeef@relay.local>\r\n\r\n"
    )
    client = _proton_client(scripted)
    pending = client.search_pending()
    assert pending == []
    client.dismiss_gmail_copies(dry_run=False)
    moved = " ".join(
        str(c[2]) for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "MOVE"
    )
    assert "1" in moved


def test_proton_search_pending_dismisses_body_stamp() -> None:
    from research_relay.stamp import stamp_line

    scripted = ScriptedProtonImap()
    scripted.search_uids = b"1"
    scripted.headers["1"] = (
        b"From: Alice <alice@candidates.edu>\r\n"
        b"Date: Thu, 20 Aug 2026 21:55:06 +0000\r\n"
        b"Message-ID: <rewritten@proton.me>\r\n\r\n"
    )
    scripted.bodies["1"] = stamp_line(b"k").encode("ascii") + b"\n\nhello\n"
    client = _proton_client(scripted)
    pending = client.search_pending()
    assert pending == []
    assert client._gmail_copies == ["proton:<rewritten@proton.me>"]


def test_proton_count_pending_returns_uid_count() -> None:
    scripted = ScriptedProtonImap()
    client = _proton_client(scripted)
    assert client.count_pending() == 2


def test_proton_search_pending_skips_stale_native() -> None:
    from types import SimpleNamespace

    scripted = ScriptedProtonImap()
    scripted.headers["1"] = (
        b"From: Alice <alice@candidates.edu>\r\n"
        b"Date: Wed, 01 Jan 2020 10:15:00 +0000\r\n"
        b"Message-ID: <native@proton.me>\r\n\r\n"
    )
    client = _proton_client(scripted)
    client._cfg.relay = SimpleNamespace(max_age_days=5)
    pending = client.search_pending()
    assert pending == []
    assert client._gmail_copies == ["proton:<copy@mail.gmail.com>"]

def test_enforce_socket_timeout_sets_sock_timeout_without_makefile() -> None:
    from research_relay.imap_timeout import enforce_socket_timeout

    class Sock:
        def __init__(self) -> None:
            self.timeout = None
            self.makefile_calls: list[str] = []

        def settimeout(self, value) -> None:
            self.timeout = value

        def makefile(self, mode: str):
            self.makefile_calls.append(mode)
            return f"file-{mode}-{self.timeout}"

    class Imap:
        def __init__(self) -> None:
            self.sock = Sock()
            self.file = "stale"

    imap = Imap()
    enforce_socket_timeout(imap, 30)
    assert imap.sock.timeout == 30.0
    assert imap.file == "stale"
    assert imap.sock.makefile_calls == []


def test_enforce_socket_timeout_does_not_assign_readonly_file() -> None:
    from research_relay.imap_timeout import enforce_socket_timeout

    class Sock:
        def __init__(self) -> None:
            self.timeout = None

        def settimeout(self, value) -> None:
            self.timeout = value

        def makefile(self, mode: str):
            return object()

    class Imap:
        def __init__(self) -> None:
            self.sock = Sock()

        @property
        def file(self):
            return None

    imap = Imap()
    enforce_socket_timeout(imap, 30)
    assert imap.sock.timeout == 30.0


def test_ssl_recv_times_out_after_starttls_shaped_wrap(tmp_path) -> None:
    import socket
    import ssl
    import subprocess
    import threading
    import time

    from research_relay.imap_timeout import enforce_socket_timeout

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    subprocess.check_call(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert), str(key))
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.check_hostname = False
    client_ctx.verify_mode = ssl.CERT_NONE

    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = lsock.getsockname()[1]

    def server() -> None:
        conn, _ = lsock.accept()
        sconn = server_ctx.wrap_socket(conn, server_side=True)
        time.sleep(5)
        sconn.close()

    threading.Thread(target=server, daemon=True).start()
    plain = socket.create_connection(("127.0.0.1", port), 2)
    plain.settimeout(2)
    ssock = client_ctx.wrap_socket(plain, server_hostname="127.0.0.1")
    ssock.makefile("rb")

    class Imap:
        def __init__(self) -> None:
            self.sock = ssock

        @property
        def file(self):
            return None

    imap = Imap()
    enforce_socket_timeout(imap, 1)
    assert imap.sock.gettimeout() == 1
    t0 = time.monotonic()
    try:
        imap.sock.recv(1024)
        raise AssertionError("SSL recv should have timed out")
    except TimeoutError:
        elapsed = time.monotonic() - t0
        assert elapsed < 2.5
    finally:
        lsock.close()


def test_close_imap_shuts_socket_without_logout() -> None:
    import socket

    from research_relay.imap_timeout import close_imap

    class Sock:
        def __init__(self) -> None:
            self.events: list[tuple] = []

        def settimeout(self, value) -> None:
            self.events.append(("timeout", value))

        def shutdown(self, how) -> None:
            self.events.append(("shutdown", how))

        def close(self) -> None:
            self.events.append(("close", None))

    class Imap:
        def __init__(self) -> None:
            self.sock = Sock()
            self.logged_out = False
            self.shut_down = False

        def logout(self) -> None:
            self.logged_out = True

        def shutdown(self) -> None:
            self.shut_down = True

    imap = Imap()
    sock = imap.sock
    close_imap(imap)
    assert imap.logged_out is False
    assert imap.shut_down is False
    assert ("shutdown", socket.SHUT_RDWR) in sock.events
    assert ("close", None) in sock.events
    assert imap.sock is None


def test_gmail_close_does_not_logout() -> None:
    scripted = ScriptedImap()

    def logout() -> tuple[str, list]:
        raise AssertionError("IMAP LOGOUT must not run on close")

    scripted.logout = logout  # type: ignore[method-assign]
    client = GmailImap.__new__(GmailImap)
    client._imap = scripted
    client.close()
    assert client._imap is None


def test_proton_close_does_not_logout() -> None:
    scripted = ScriptedProtonImap()

    def logout() -> tuple[str, list]:
        raise AssertionError("IMAP LOGOUT must not run on close")

    scripted.logout = logout  # type: ignore[method-assign]
    client = _proton_client(scripted)
    client.close()
    assert client._imap is None


def test_proton_fetch_by_message_id_tries_sent_then_inbox_then_pending() -> None:
    class Scripted(ScriptedProtonImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            self.commands.append(("uid", command, args))
            verb = command.upper()
            if verb == "SEARCH":
                needle = " ".join(str(a) for a in args)
                selected = self.selected or ""
                if "native@proton.me" in needle and "sent" in selected.lower():
                    return "OK", [b"9"]
                return "OK", [b""]
            if verb == "FETCH":
                return "OK", [(b"BODY[] {1}", self.bodies["1"])]
            return "OK", [b""]

    client = _proton_client(Scripted())
    raw = client.fetch_by_message_id("<native@proton.me>")
    assert b"native@proton.me" in raw
    selects = [c[1] for c in client._imap.commands if c[0] == "select"]
    assert any("sent" in str(item).lower() for item in selects)


def test_proton_fetch_by_message_id_miss_is_temporary() -> None:
    from research_relay.exceptions import TemporaryRelayError

    class Empty(ScriptedProtonImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            self.commands.append(("uid", command, args))
            if str(command).upper() == "SEARCH":
                return "OK", [b""]
            return super().uid(command, *args)

    client = _proton_client(Empty())
    with pytest.raises(TemporaryRelayError, match="not found"):
        client.fetch_by_message_id("<missing@proton.me>")


def test_proton_collect_recent_native_skips_gmail_copies_and_old_mail() -> None:
    now = __import__("datetime").datetime(2026, 8, 28, 14, 0, tzinfo=__import__("datetime").timezone.utc)
    scripted = ScriptedProtonImap()
    scripted.search_uids = b"1 2 3"
    scripted.headers["1"] = (
        b"From: Alice <alice@proton.me>\r\n"
        b"Date: Thu, 27 Aug 2026 15:00:00 +0000\r\n"
        b"Message-ID: <native@proton.me>\r\n\r\n"
    )
    scripted.headers["3"] = (
        b"From: Alice <alice@proton.me>\r\n"
        b"Date: Mon, 24 Aug 2026 15:00:00 +0000\r\n"
        b"Message-ID: <old@proton.me>\r\n\r\n"
    )
    scripted.bodies["1"] = scripted.headers["1"] + b"hello\r\n"
    scripted.bodies["3"] = scripted.headers["3"] + b"old\r\n"
    client = _proton_client(scripted)
    keys = client.collect_recent_native(hours=48, now=now)
    assert keys == ["proton:<native@proton.me>"]
    search = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "SEARCH"]
    assert any("SINCE" in str(c[2]) for c in search)


def test_proton_collect_recent_native_since_date() -> None:
    now = __import__("datetime").datetime(2026, 8, 28, 14, 0, tzinfo=__import__("datetime").timezone.utc)
    since = __import__("datetime").datetime(2026, 8, 15, 0, 0, tzinfo=__import__("datetime").timezone.utc)
    scripted = ScriptedProtonImap()
    scripted.search_uids = b"1 3"
    scripted.headers["1"] = (
        b"From: Alice <alice@proton.me>\r\n"
        b"Date: Sat, 15 Aug 2026 12:00:00 +0000\r\n"
        b"Message-ID: <mid@proton.me>\r\n\r\n"
    )
    scripted.headers["3"] = (
        b"From: Alice <alice@proton.me>\r\n"
        b"Date: Fri, 14 Aug 2026 12:00:00 +0000\r\n"
        b"Message-ID: <old@proton.me>\r\n\r\n"
    )
    scripted.bodies["1"] = scripted.headers["1"] + b"hello\r\n"
    scripted.bodies["3"] = scripted.headers["3"] + b"old\r\n"
    client = _proton_client(scripted)
    keys = client.collect_recent_native(since=since, now=now)
    assert keys == ["proton:<mid@proton.me>"]
    search = [c for c in scripted.commands if c[0] == "uid" and str(c[1]).upper() == "SEARCH"]
    assert any("15-Aug-2026" in str(c[2]) for c in search)


def test_gmail_search_timeout_is_temporary() -> None:
    from research_relay.exceptions import TemporaryRelayError

    class Slow(ScriptedImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            raise TimeoutError("timed out")

    client = GmailImap.__new__(GmailImap)
    client._imap = Slow()
    with pytest.raises(TemporaryRelayError, match="timed out"):
        client.search("label:relay/pending")


def test_proton_search_timeout_is_temporary() -> None:
    from research_relay.exceptions import TemporaryRelayError

    class Slow(ScriptedProtonImap):
        def uid(self, command: str, *args) -> tuple[str, list]:
            raise TimeoutError("timed out")

    client = _proton_client(Slow())
    with pytest.raises(TemporaryRelayError, match="timed out"):
        client.search_pending()

