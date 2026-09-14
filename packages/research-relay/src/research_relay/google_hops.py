from __future__ import annotations

import re

_GOOGLE_HINT = re.compile(
    rb"(mx\.google\.com|mail-[\w.-]*\.google\.com|x-google-|x-gmail-|x-gm-|"
    rb"google\.com\b|smtp\.google\.com)",
    re.IGNORECASE,
)


def has_google_hops(raw: bytes) -> bool:
    """True when RFC822 bytes look like they transited Google's mail system."""
    header = raw.split(b"\r\n\r\n", 1)[0] if raw else b""
    if b"\n\n" in raw and (not header or len(header) == len(raw)):
        header = raw.split(b"\n\n", 1)[0]
    return bool(_GOOGLE_HINT.search(header))
