from __future__ import annotations

import html
import os
import re
from datetime import datetime

from research_relay.attachments import sanitize_filename
from research_relay.redact import redact_text

_SPACES = re.compile(r"\s+")


def format_archive_date(when: datetime) -> str:
    return when.strftime("%Y-%m-%d")


def _safe_subject(subject: str, private_address: str) -> str:
    text = (subject or "").replace("\\", "_").replace("/", "_")
    text = _SPACES.sub("_", text).strip("_")
    return sanitize_filename(text or "no_subject", private_address)


def archive_pdf_name(
    when: datetime,
    subject: str,
    original_name: str,
    *,
    private_address: str,
) -> str:
    date_prefix = format_archive_date(when)
    sanitized_subject = _safe_subject(subject, private_address)
    original = sanitize_filename(original_name or "attachment.pdf", private_address)
    name = f"{date_prefix}_{sanitized_subject}_{original}"
    if len(name) > 200:
        stem, ext = os.path.splitext(original)
        if not ext.lower() == ".pdf":
            ext = ".pdf"
        name = f"{date_prefix}_{stem[:150]}{ext}"
        if len(name) > 200:
            name = name[: 200 - len(ext)] + ext
    return name


def archive_doc_name(
    when: datetime,
    subject: str,
    original_name: str,
    *,
    private_address: str,
) -> str:
    pdf = archive_pdf_name(when, subject, original_name, private_address=private_address)
    if pdf.lower().endswith(".pdf"):
        return pdf[: -len(".pdf")]
    return os.path.splitext(pdf)[0]


def archive_html_name(when: datetime, subject: str, *, private_address: str) -> str:
    date_prefix = format_archive_date(when)
    sanitized_subject = _safe_subject(subject, private_address)
    name = f"{date_prefix}_{sanitized_subject}.html"
    if len(name) > 200:
        name = name[: 196] + ".html"
    return name


def archive_html_document(
    *,
    sender: str,
    date_text: str,
    subject: str,
    body: str,
    private_address: str,
) -> str:
    safe_sender = html.escape(redact_text(sender or "", private_address))
    safe_date = html.escape(redact_text(date_text or "", private_address))
    safe_subject = html.escape(redact_text(subject or "", private_address))
    safe_body = html.escape(redact_text(body or "", private_address)).replace("\n", "<br>\n")
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n"
        f"<title>{safe_subject}</title>\n</head>\n<body>\n"
        f"<p><strong>From:</strong> {safe_sender}</p>\n"
        f"<p><strong>Date:</strong> {safe_date}</p>\n"
        f"<p><strong>Subject:</strong> {safe_subject}</p>\n"
        f"<div>{safe_body}</div>\n</body>\n</html>\n"
    )
