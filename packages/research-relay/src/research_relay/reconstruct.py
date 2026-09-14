from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from research_relay.attachments import (
    AttachmentDecision,
    AttachmentPolicy,
    AttachmentResult,
    evaluate_attachment,
)
from research_relay.domain import extract_sender_mailbox
from research_relay.htmltext import html_to_text
from research_relay.message_id import make_message_id
from research_relay.quotes import strip_quoted_history
from research_relay.redact import redact_text
from research_relay.stamp import STAMP_HEADER, stamp_line, stamp_value
from research_relay.subject import clean_subject

FORBIDDEN_HEADER_PREFIXES = (
    "x-google-",
    "x-gmail-",
    "x-gm-",
)

FORBIDDEN_HEADERS = {
    "received",
    "delivered-to",
    "return-path",
    "message-id",
    "references",
    "in-reply-to",
    "authentication-results",
    "dkim-signature",
    "arc-seal",
    "arc-message-signature",
    "arc-authentication-results",
    "x-received",
    "x-forwarded-to",
    "x-forwarded-for",
    "x-original-from",
    "x-original-sender",
    "x-original-to",
    "x-originating-ip",
    "received-spf",
}


@dataclass(frozen=True)
class ReconstructionSettings:
    proton_from: str
    reply_to: str
    private_address: str
    hmac_key: bytes
    message_id_domain: str
    attachment_policy: AttachmentPolicy


@dataclass
class Reconstruction:
    message: EmailMessage
    attachments: list[AttachmentResult]
    sender_address: str
    notes: list[str]


def parse_rfc822(raw: bytes) -> EmailMessage:
    return BytesParser(policy=policy.default).parsebytes(raw)


def reconstruct_message(
    original: EmailMessage,
    *,
    gmail_msgid: str,
    settings: ReconstructionSettings,
) -> Reconstruction:
    private = settings.private_address
    subject = redact_text(clean_subject(str(original.get("Subject") or "")), private)
    date_header = redact_text(_original_date(original), private)
    sender_line, sender_address = _sender_attribution(original, private)
    body = _extract_body(original)
    body = strip_quoted_history(body)
    body = redact_text(body, private)
    stamp = stamp_line(settings.hmac_key)
    preamble = "\n".join(part for part in (sender_line, date_header, stamp) if part)
    if not body.strip():
        body = "[No plain-text content could be extracted]"
    full_body = f"{preamble}\n\n{body.strip()}\n"

    outgoing = EmailMessage()
    outgoing["From"] = settings.proton_from
    outgoing["To"] = "undisclosed-recipients:;"
    outgoing["Reply-To"] = settings.reply_to
    outgoing["Subject"] = subject or "(no subject)"
    if date_header:
        original_date = original.get("Date")
        parsed = _try_parse_date(str(original_date) if original_date else "")
        if parsed is not None:
            outgoing["Date"] = parsed
    outgoing["Message-ID"] = make_message_id(
        gmail_msgid, settings.hmac_key, settings.message_id_domain
    )
    outgoing["Auto-Submitted"] = "auto-generated"
    outgoing[STAMP_HEADER] = stamp_value(settings.hmac_key)
    outgoing.set_content(full_body)
    _drop_forbidden_headers(outgoing)

    notes: list[str] = []
    kept: list[AttachmentResult] = []
    used_bytes = 0
    used_names: set[str] = set()
    for filename, payload, content_type in _iter_attachments(original):
        if (filename or "").lower().endswith(".eml") or content_type == "message/rfc822":
            notes.append("skipped original message/rfc822 part")
            continue
        result = evaluate_attachment(
            filename=filename or "attachment",
            payload=payload,
            content_type=content_type,
            used_bytes=used_bytes,
            policy=settings.attachment_policy,
            used_names=used_names,
        )
        kept.append(result)
        if result.action != AttachmentDecision.ALLOW:
            notes.append(f"{result.action.value} attachment {result.safe_filename}: {result.reason}")
            continue
        maintype, _, subtype = (result.content_type or "application/octet-stream").partition("/")
        outgoing.add_attachment(
            result.payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=result.safe_filename,
        )
        used_bytes += len(result.payload)

    _drop_forbidden_headers(outgoing)
    return Reconstruction(
        message=outgoing,
        attachments=kept,
        sender_address=sender_address,
        notes=notes,
    )


def _drop_forbidden_headers(message: EmailMessage) -> None:
    allowed = {
        "from",
        "to",
        "reply-to",
        "subject",
        "date",
        "message-id",
        "mime-version",
        "content-type",
        "content-transfer-encoding",
        "content-disposition",
        "auto-submitted",
        STAMP_HEADER.lower(),
    }
    for key in list(message.keys()):
        lower = key.lower()
        if lower in allowed:
            continue
        if lower in FORBIDDEN_HEADERS or any(lower.startswith(prefix) for prefix in FORBIDDEN_HEADER_PREFIXES):
            del message[key]


def _try_parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _original_date(original: EmailMessage) -> str:
    value = str(original.get("Date") or "").strip()
    if not value:
        return ""
    return f"Date: {value}"


def _sender_attribution(original: EmailMessage, private: str) -> tuple[str, str]:
    raw_from = str(original.get("From") or "").strip()
    try:
        mailbox = extract_sender_mailbox(raw_from)
        display = mailbox.display_name or mailbox.address
        label = f"{display} <{mailbox.address}>" if mailbox.display_name else mailbox.address
        sender_address = mailbox.address
    except ValueError:
        label = raw_from or "unknown"
        sender_address = ""
    return f"Sender: {redact_text(label, private)}", sender_address


def _decode_part_text(part: EmailMessage) -> str:
    try:
        content = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return str(part.get_payload() or "")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def _extract_body(original: EmailMessage) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in original.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        ctype = part.get_content_type()
        if disposition == "attachment":
            continue
        if filename and ctype not in {"text/plain", "text/html"}:
            continue
        try:
            if ctype == "text/plain":
                plain_parts.append(_decode_part_text(part))
            elif ctype == "text/html":
                html_parts.append(_decode_part_text(part))
        except Exception:
            continue
    if plain_parts:
        return plain_parts[0]
    if html_parts:
        return html_to_text(html_parts[0])
    return ""


def _iter_attachments(original: EmailMessage) -> list[tuple[str | None, bytes, str]]:
    found: list[tuple[str | None, bytes, str]] = []
    for part in original.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        ctype = part.get_content_type()
        is_body_text = ctype in {"text/plain", "text/html"} and disposition != "attachment"
        if is_body_text and not filename:
            continue
        if disposition not in {"attachment", "inline"} and not filename:
            if ctype in {"text/plain", "text/html"}:
                continue
        if ctype in {"text/plain", "text/html"} and disposition != "attachment" and not filename:
            continue
        if not filename and disposition != "attachment" and ctype in {"text/plain", "text/html"}:
            continue
        include = disposition == "attachment" or bool(filename)
        if not include:
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            payload = b""
        if not isinstance(payload, bytes):
            payload = str(payload).encode("utf-8", errors="replace")
        found.append((filename, payload, ctype))
    return found
