from __future__ import annotations

import socket

from research_relay.exceptions import TemporaryRelayError


def enforce_socket_timeout(imap: object, seconds: float) -> None:
    """Apply a read/write timeout to the IMAP socket.

    Python 3.14 imaplib.readline uses ``self.sock.recv``, not makefile().
    ``IMAP4.file`` is a read-only property; assigning it raises AttributeError.
    STARTTLS ``wrap_socket`` + makefile can leave SSL recv with timeout None,
    so LOGIN then blocks forever. Re-set timeout on the SSL socket (and its
    underlying socket if present) without touching ``file``.
    """
    timeout = max(1.0, float(seconds))
    _set_timeout(getattr(imap, "sock", None), timeout)


def _set_timeout(sock: object | None, timeout: float) -> None:
    if sock is None:
        return
    setter = getattr(sock, "settimeout", None)
    if callable(setter):
        setter(timeout)
    for attr in ("socket", "_sock"):
        inner = getattr(sock, attr, None)
        if inner is not None and inner is not sock:
            inner_setter = getattr(inner, "settimeout", None)
            if callable(inner_setter):
                try:
                    inner_setter(timeout)
                except Exception:
                    pass


def close_imap(imap: object) -> None:
    """Drop the socket without IMAP LOGOUT or imaplib shutdown().

    LOGOUT and IMAP4.shutdown() both block on SSL read. After a finished
    run or Ctrl+C that hung the session; the server will drop it.
    """
    if imap is None:
        return
    sock = getattr(imap, "sock", None)
    try:
        if sock is not None:
            sock.settimeout(0.2)
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
    except Exception:
        pass
    for attr in ("file", "sock"):
        try:
            setattr(imap, attr, None)
        except Exception:
            pass


def imap_timeout(exc: BaseException) -> TemporaryRelayError:
    return TemporaryRelayError(f"IMAP timed out: {exc.__class__.__name__}")
