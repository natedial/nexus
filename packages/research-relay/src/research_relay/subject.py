from __future__ import annotations

import re

_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:)+\s*", re.IGNORECASE)


def clean_subject(subject: str) -> str:
    if not subject:
        return ""
    cleaned = subject.strip()
    while True:
        updated = _PREFIX.sub("", cleaned, count=1)
        if updated == cleaned:
            break
        cleaned = updated.strip()
    return cleaned
