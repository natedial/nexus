"""Render body-only research emails as searchable PDFs."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import reportlab
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from research_relay.redact import redact_text

_FONT_NAME = "RelayVera"
_FONT_SIZE = 10
_LEADING = 14
_MARGIN = 54


def render_body_pdf(
    *,
    sender: str,
    date_text: str,
    subject: str,
    body: str,
    private_address: str,
) -> bytes:
    """Return a deterministic, searchable PDF containing the safe email body."""
    _register_font()
    safe_sender = redact_text(sender or "", private_address)
    safe_date = redact_text(date_text or "", private_address)
    safe_subject = redact_text(subject or "", private_address)
    safe_body = redact_text(body or "", private_address)

    output = BytesIO()
    pdf = Canvas(
        output,
        pagesize=letter,
        pageCompression=1,
        invariant=1,
    )
    pdf.setTitle(safe_subject or "Research email")
    width, height = letter
    max_width = width - (2 * _MARGIN)
    y = height - _MARGIN

    def new_page() -> float:
        pdf.showPage()
        pdf.setFont(_FONT_NAME, _FONT_SIZE)
        return height - _MARGIN

    pdf.setFont(_FONT_NAME, _FONT_SIZE)
    lines = [
        f"From: {safe_sender}",
        f"Date: {safe_date}",
        f"Subject: {safe_subject}",
        "",
        *safe_body.splitlines(),
    ]
    for raw_line in lines:
        wrapped = _wrap_line(raw_line, max_width)
        for line in wrapped:
            if y < _MARGIN + _LEADING:
                y = new_page()
            pdf.drawString(_MARGIN, y, line)
            y -= _LEADING

    pdf.save()
    return output.getvalue()


def _register_font() -> None:
    if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    pdfmetrics.registerFont(TTFont(_FONT_NAME, str(font_path)))


def _wrap_line(text: str, max_width: float) -> list[str]:
    if not text:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidates = _split_token(word, max_width)
        for candidate in candidates:
            proposed = f"{current} {candidate}".strip()
            if current and pdfmetrics.stringWidth(proposed, _FONT_NAME, _FONT_SIZE) > max_width:
                lines.append(current)
                current = candidate
            else:
                current = proposed
    if current:
        lines.append(current)
    return lines or [""]


def _split_token(token: str, max_width: float) -> list[str]:
    if pdfmetrics.stringWidth(token, _FONT_NAME, _FONT_SIZE) <= max_width:
        return [token]
    chunks: list[str] = []
    current = ""
    for char in token:
        proposed = current + char
        if current and pdfmetrics.stringWidth(proposed, _FONT_NAME, _FONT_SIZE) > max_width:
            chunks.append(current)
            current = char
        else:
            current = proposed
    if current:
        chunks.append(current)
    return chunks
