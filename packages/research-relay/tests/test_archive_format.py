from datetime import datetime

from research_relay.archive_format import (
    archive_doc_name,
    archive_html_document,
    archive_html_name,
    archive_pdf_name,
)


def test_pdf_name_uses_date_and_sanitized_subject() -> None:
    name = archive_pdf_name(
        datetime(2026, 8, 28),
        "Q3 results / draft",
        "report.pdf",
        private_address="hidden@gmail.com",
    )
    assert name.startswith("2026-08-28_")
    assert name.endswith("_report.pdf")
    assert "/" not in name
    assert " " not in name.split("_", 1)[1].replace("_", "")


def test_pdf_name_redacts_private_address() -> None:
    name = archive_pdf_name(
        datetime(2026, 8, 1),
        "for hidden@gmail.com",
        "a.pdf",
        private_address="hidden@gmail.com",
    )
    assert "hidden@gmail.com" not in name.lower()
    assert "[redacted]" in name.lower() or "redacted" in name.lower()


def test_pdf_name_truncates_over_200_chars() -> None:
    original = ("x" * 180) + ".pdf"
    name = archive_pdf_name(datetime(2026, 1, 2), "subj", original, private_address="")
    assert len(name) <= 200
    assert name.endswith(".pdf")
    assert name.startswith("2026-01-02_")


def test_doc_name_strips_pdf_suffix() -> None:
    pdf = archive_pdf_name(datetime(2026, 8, 28), "Memo", "scan.pdf", private_address="")
    doc = archive_doc_name(datetime(2026, 8, 28), "Memo", "scan.pdf", private_address="")
    assert doc == pdf[: -len(".pdf")]
    assert not doc.lower().endswith(".pdf")


def test_html_name() -> None:
    name = archive_html_name(datetime(2026, 8, 28), "Hello / there", private_address="")
    assert name.startswith("2026-08-28_")
    assert name.endswith(".html")
    assert "/" not in name
    assert " " not in name


def test_html_document_escapes_and_omits_private_address() -> None:
    body = "See <script>alert(1)</script> hidden@gmail.com"
    html = archive_html_document(
        sender='Alice <a@candidates.edu>',
        date_text="Fri, 28 Aug 2026",
        subject='Q&A <draft>',
        body=body,
        private_address="hidden@gmail.com",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "hidden@gmail.com" not in html
    assert "Q&amp;A" in html or "Q&A" not in html or "&amp;" in html
    assert "Alice" in html
