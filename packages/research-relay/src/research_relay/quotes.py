from __future__ import annotations

import re

_SEPARATORS = (
    re.compile(r"^-----Original Message-----", re.MULTILINE),
    re.compile(r"^-----Forwarded Message-----", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^----- Forwarded Message -----", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Begin forwarded message:\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{32,}\s*$", re.MULTILINE),
    re.compile(
        r"^On [^\n]{5,160}?(?:\n<[^>\n]+>)?\s*wrote:\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(r"^From:\s.+\nSent:\s", re.MULTILINE | re.IGNORECASE),
)


def strip_quoted_history(body: str) -> str:
    if not body:
        return body
    earliest: int | None = None
    for pattern in _SEPARATORS:
        match = pattern.search(body)
        if not match:
            continue
        prefix = body[: match.start()].strip()
        if not prefix:
            continue
        if earliest is None or match.start() < earliest:
            earliest = match.start()
    if earliest is None:
        return body
    return body[:earliest].rstrip() + "\n"
