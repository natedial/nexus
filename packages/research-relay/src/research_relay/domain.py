from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from email.utils import parseaddr


@dataclass(frozen=True)
class Mailbox:
    address: str
    domain: str
    local_part: str
    display_name: str


def extract_sender_mailbox(from_header: str) -> Mailbox:
    display, address = parseaddr(from_header or "")
    address = (address or "").strip()
    if address.count("@") != 1:
        raise ValueError("From header does not contain a single mailbox address")
    local, domain = address.rsplit("@", 1)
    local = local.strip()
    domain = domain.strip().rstrip(".").lower()
    if not local or not domain or "." not in domain:
        raise ValueError("From header mailbox is missing a valid domain")
    return Mailbox(
        address=f"{local.lower()}@{domain}",
        domain=domain,
        local_part=local.lower(),
        display_name=display.strip(),
    )


def address_is_one_of(from_header: str, addresses: Iterable[str]) -> bool:
    try:
        mailbox = extract_sender_mailbox(from_header)
    except ValueError:
        return False
    owned = {str(item).strip().lower() for item in addresses if str(item).strip()}
    return mailbox.address in owned


def message_id_from_domain(message_id: str, domain: str) -> bool:
    text = (message_id or "").strip().strip("<>").strip()
    host = (domain or "").strip().lower().lstrip("@").rstrip(".")
    if not text or not host or "@" not in text:
        return False
    id_host = text.rsplit("@", 1)[-1].strip().rstrip(".").lower()
    return id_host == host


def domain_allowed(
    from_header: str,
    allowed_domains: list[str],
    allow_subdomains: bool,
) -> bool:
    try:
        mailbox = extract_sender_mailbox(from_header)
    except ValueError:
        return False
    return _domain_matches(mailbox.domain, allowed_domains, allow_subdomains)


def _domain_matches(domain: str, allowed_domains: list[str], allow_subdomains: bool) -> bool:
    domain = domain.lower().rstrip(".")
    for raw in allowed_domains:
        allowed = raw.lower().strip().rstrip(".")
        if not allowed:
            continue
        if domain == allowed:
            return True
        if allow_subdomains and domain.endswith("." + allowed):
            return True
    return False
