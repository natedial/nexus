from __future__ import annotations

import re

_REDACTED = "[redacted]"


def _variants(address: str) -> list[str]:
    address = address.strip()
    if "@" not in address:
        return [address] if address else []
    local, _, domain = address.partition("@")
    variants = [
        address,
        f"{local}@{domain}",
        f"{local}&#64;{domain}",
        f"{local}&#x40;{domain}",
        f"{local}&#X40;{domain}",
        f"{local}%40{domain}",
        f"{local} (at) {domain}",
        f"{local} [at] {domain}",
    ]
    return variants


def redact_text(text: str, private_address: str) -> str:
    if not text or not private_address:
        return text
    out = text
    for variant in _variants(private_address):
        out = re.sub(re.escape(variant), _REDACTED, out, flags=re.IGNORECASE)
    return out


def redact_filename(name: str, private_address: str) -> str:
    return redact_text(name or "", private_address)
