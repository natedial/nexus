from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

from research_relay.attachments import AttachmentDecision, AttachmentResult
from research_relay.intake_handoff import write_intake_handoff
from research_relay.ledger import ArchiveRow
from research_relay.reconstruct import Reconstruction


def _archive_row() -> ArchiveRow:
    return ArchiveRow(
        gmail_msgid="proton:<abc@example.com>",
        message_id="<abc@example.com>",
        kind="pdfs",
        expected_names=["2026-03-21_note_report.pdf"],
        pdf_ids={"2026-03-21_note_report.pdf": "drive-pdf-1"},
        doc_ids={"2026-03-21_note_report.pdf": "drive-doc-1"},
        html_id="",
        last_error="",
        find_failures=0,
        unrecoverable=False,
        enqueued_at="2026-03-21T00:00:00Z",
        updated_at="2026-03-21T00:00:00Z",
    )


def test_write_intake_handoff_writes_manifest_and_pdf(tmp_path: Path) -> None:
    message = EmailMessage()
    message["Subject"] = "Rates note"
    message.set_content("Sanitized body")
    reconstructed = Reconstruction(
        message=message,
        attachments=[
            AttachmentResult(
                action=AttachmentDecision.ALLOW,
                reason="ok",
                safe_filename="report.pdf",
                payload=b"%PDF-1.4 test",
                content_type="application/pdf",
            )
        ],
        sender_address="sender@example.com",
        notes=[],
    )
    pdf_name = "2026-03-21_note_report.pdf"
    manifest = write_intake_handoff(
        tmp_path,
        relay_key="proton:<abc@example.com>",
        reconstructed=reconstructed,
        original_date="Mon, 21 Mar 2026 12:00:00 +0000",
        row=_archive_row(),
        pdf_payloads={pdf_name: b"%PDF-1.4 test"},
        bundle_id="bundle123",
    )
    assert manifest is not None
    bundle_dir = tmp_path / "bundle123"
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / pdf_name).read_bytes() == b"%PDF-1.4 test"
    loaded = (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    assert "proton:<abc@example.com>" in loaded
    assert manifest.content_hash
