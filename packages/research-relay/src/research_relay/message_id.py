from __future__ import annotations

import hashlib
import hmac


def make_message_id(gmail_msgid: str, hmac_key: bytes, domain: str) -> str:
    digest = hmac.new(hmac_key, str(gmail_msgid).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"<{digest[:32]}@{domain}>"
