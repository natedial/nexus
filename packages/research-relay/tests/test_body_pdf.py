from io import BytesIO

from pypdf import PdfReader

from research_relay.body_pdf import render_body_pdf


def test_render_body_pdf_is_searchable_and_redacted() -> None:
    payload = render_body_pdf(
        sender="Alice <alice@example.com>",
        date_text="Fri, 28 Aug 2026",
        subject="Rates — morning note",
        body="First line\nSecond line for hidden@gmail.com",
        private_address="hidden@gmail.com",
    )

    assert payload.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    assert "Rates" in text
    assert "First line" in text
    assert "[redacted]" in text
    assert "hidden@gmail.com" not in text


def test_render_body_pdf_adds_pages_for_long_messages() -> None:
    payload = render_body_pdf(
        sender="Alice <alice@example.com>",
        date_text="Fri, 28 Aug 2026",
        subject="Long note",
        body="\n".join(f"Research line {number}" for number in range(250)),
        private_address="",
    )

    assert len(PdfReader(BytesIO(payload)).pages) > 1
