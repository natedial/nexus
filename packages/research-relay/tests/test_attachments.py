from research_relay.attachments import (
    AttachmentDecision,
    AttachmentPolicy,
    evaluate_attachment,
    sanitize_filename,
)


def _policy(**kwargs) -> AttachmentPolicy:
    defaults = dict(
        max_individual_bytes=10_000,
        max_combined_bytes=20_000,
        blocked_extensions=(".exe", ".js", ".zip", ".docm", ".xlsm", ".pptm", ".sh"),
        allowed_extensions=(),
        on_prohibited="skip",
        private_address="private.user@gmail.com",
    )
    defaults.update(kwargs)
    return AttachmentPolicy(**defaults)


def test_sanitize_filename_strips_path_traversal() -> None:
    name = sanitize_filename("../../etc/passwd.exe", "private.user@gmail.com")
    assert ".." not in name
    assert "/" not in name
    assert "\\" not in name


def test_sanitize_filename_redacts_private_address() -> None:
    name = sanitize_filename("cv-private.user@gmail.com.pdf", "private.user@gmail.com")
    assert "gmail.com" not in name.lower()


def test_sanitize_preserves_unicode_letters() -> None:
    name = sanitize_filename("résumé.pdf", "private.user@gmail.com")
    assert "résumé.pdf" == name or "résumé" in name


def test_blocks_dangerous_extension() -> None:
    decision = evaluate_attachment(
        filename="payload.exe",
        payload=b"MZ",
        content_type="application/octet-stream",
        used_bytes=0,
        policy=_policy(),
    )
    assert decision.action == AttachmentDecision.SKIP
    assert "extension" in decision.reason


def test_blocks_macro_enabled_office() -> None:
    decision = evaluate_attachment(
        filename="budget.xlsm",
        payload=b"PK",
        content_type="application/vnd.ms-excel.sheet.macroEnabled.12",
        used_bytes=0,
        policy=_policy(),
    )
    assert decision.action == AttachmentDecision.SKIP


def test_skips_oversized_individual_attachment() -> None:
    decision = evaluate_attachment(
        filename="talk.pdf",
        payload=b"x" * 11_000,
        content_type="application/pdf",
        used_bytes=0,
        policy=_policy(),
    )
    assert decision.action == AttachmentDecision.SKIP
    assert "size" in decision.reason


def test_skips_when_combined_size_exceeded() -> None:
    decision = evaluate_attachment(
        filename="talk.pdf",
        payload=b"x" * 5_000,
        content_type="application/pdf",
        used_bytes=16_000,
        policy=_policy(),
    )
    assert decision.action == AttachmentDecision.SKIP
    assert "combined" in decision.reason


def test_quarantines_when_configured() -> None:
    decision = evaluate_attachment(
        filename="run.sh",
        payload=b"#!/bin/sh\n",
        content_type="text/x-shellscript",
        used_bytes=0,
        policy=_policy(on_prohibited="quarantine"),
    )
    assert decision.action == AttachmentDecision.QUARANTINE


def test_allows_pdf_under_limits() -> None:
    decision = evaluate_attachment(
        filename="cv.pdf",
        payload=b"%PDF-1.4\n",
        content_type="application/pdf",
        used_bytes=0,
        policy=_policy(),
    )
    assert decision.action == AttachmentDecision.ALLOW
    assert decision.safe_filename == "cv.pdf"


def test_duplicate_filenames_get_suffix() -> None:
    first = sanitize_filename("cv.pdf", "private.user@gmail.com")
    second = sanitize_filename("cv.pdf", "private.user@gmail.com", used={"cv.pdf"})
    assert first == "cv.pdf"
    assert second != first
    assert second.startswith("cv")
    assert second.endswith(".pdf")
