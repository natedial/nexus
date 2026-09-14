from __future__ import annotations

import hashlib
import hmac

STAMP_HEADER = "X-Research-Relay"
STAMP_PURPOSE = b"research-relay-stamp-v1"


def stamp_token(hmac_key: bytes) -> str:
    digest = hmac.new(hmac_key, STAMP_PURPOSE, hashlib.sha256).hexdigest()
    return digest[:16]


def stamp_value(hmac_key: bytes) -> str:
    return f"v1={stamp_token(hmac_key)}"


def stamp_line(hmac_key: bytes) -> str:
    return f"{STAMP_HEADER}: {stamp_value(hmac_key)}"


def is_auto_submitted(message) -> bool:
    raw = str(message.get("Auto-Submitted") or "").strip().lower()
    return bool(raw) and raw != "no"


def header_has_stamp(message, hmac_key: bytes) -> bool:
    raw = str(message.get(STAMP_HEADER) or "").strip()
    return raw.lower() == stamp_value(hmac_key).lower()


def text_has_stamp(text: str, hmac_key: bytes) -> bool:
    needle = stamp_line(hmac_key).lower()
    return needle in (text or "").lower()


def message_is_own_output(message, hmac_key: bytes) -> bool:
    if is_auto_submitted(message):
        return True
    if header_has_stamp(message, hmac_key):
        return True
    body = ""
    try:
        part = message.get_body(preferencelist=("plain",))
        if part is not None:
            body = str(part.get_content() or "")
    except Exception:
        body = ""
    if not body:
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            body = payload.decode("utf-8", errors="replace")
        elif isinstance(payload, str):
            body = payload
    return text_has_stamp(body, hmac_key)


def raw_is_own_output(header: bytes, hmac_key: bytes, body_prefix: bytes = b"") -> bool:
    blob = (header or b"") + b"\n" + (body_prefix or b"")
    text = blob.decode("utf-8", errors="replace")
    if _raw_auto_submitted(text):
        return True
    return text_has_stamp(text, hmac_key)


def _raw_auto_submitted(text: str) -> bool:
    for line in text.splitlines():
        if line.lower().startswith("auto-submitted:"):
            value = line.split(":", 1)[1].strip().lower()
            return bool(value) and value != "no"
    return False
