from __future__ import annotations

import logging
import signal

log = logging.getLogger("research_relay")


def install_max_runtime(seconds: int) -> None:
    """Abort the process after *seconds* even if an SSL/IMAP read ignores socket timeouts.

    Python retries interrupted syscalls (PEP 475), so the handler must raise
    SystemExit rather than TimeoutError. TimeoutError is swallowed by
    `except Exception` around label updates.
    """
    limit = int(seconds or 0)
    if limit <= 0:
        return

    def _handler(signum, frame) -> None:
        log.error("max runtime exceeded seconds=%s", limit)
        raise SystemExit(1)

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(limit)


def clear_max_runtime() -> None:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
