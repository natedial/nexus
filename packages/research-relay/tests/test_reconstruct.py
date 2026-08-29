from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import pytest

from research_relay.attachments import AttachmentPolicy
from research_relay.reconstruct import ReconstructionSettings, reconstruct_message

FIXTURES = Path(__file__).parent / "fixtures"
PRIVATE = "private.user@gmail.com"
PROTON_FROM = "relay@proton.me"
PROTON_REPLY_TO = "relay-reply@proton.me"
COLLEAGUES = ["c1@proton.me", "c2@example.org"]
HMAC_KEY = b"unit-test-hmac-key"


FORBIDDEN_HEADERS = {
    "received",
    "delivered-to",
    "return-path",
    "references",
    "in-reply-to",
    "authentication-results",
}


def _parse(name: str) -> EmailMessage:
    data = (FIXTURES / name).read_bytes()
    return BytesParser(policy=policy.default).parsebytes(data)


def _settings(**kwargs) -> ReconstructionSettings:
    values = dict(
        proton_from=PROTON_FROM,
        reply_to=PROTON_REPLY_TO,
        private_address=PRIVATE,
        hmac_key=HMAC_KEY,
        message_id_domain="relay.local",
        attachment_policy=AttachmentPolicy(
            max_individual_bytes=50_000,
            max_combined_bytes=100_000,
            blocked_extensions=(".exe", ".js", ".zip", ".docm", ".xlsm", ".pptm", ".sh"),
            allowed_extensions=(),
            on_prohibited="skip",
            private_address=PRIVATE,
        ),
    )
    values.update(kwargs)
    return ReconstructionSettings(**values)


def _rebuild(name: str, gmail_msgid: str = "12345") -> EmailMessage:
    original = _parse(name)
    result = reconstruct_message(original, gmail_msgid=gmail_msgid, settings=_settings())
    return result.message


def test_plain_text_rebuilds_new_message() -> None:
    msg = _rebuild("plain_text.eml")
    assert msg["From"] == PROTON_FROM
    assert msg["To"] == "undisclosed-recipients:;"
    assert msg["Reply-To"] == PROTON_REPLY_TO
    assert msg["Bcc"] is None
    assert msg["Subject"] == "Application materials"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "available next week" in body
    assert "Alice Candidate" in body
    assert "alice@candidates.edu" in body


def test_reconstructed_mail_carries_relay_stamp() -> None:
    from research_relay.stamp import STAMP_HEADER, stamp_line, stamp_value

    msg = _rebuild("plain_text.eml")
    assert msg[STAMP_HEADER] == stamp_value(HMAC_KEY)
    assert msg["Auto-Submitted"] == "auto-generated"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert stamp_line(HMAC_KEY) in body


def test_original_transport_and_threading_headers_are_absent() -> None:
    msg = _rebuild("plain_text.eml")
    lowered = {k.lower() for k in msg.keys()}
    for header in FORBIDDEN_HEADERS:
        assert header not in lowered
    for key in msg.keys():
        assert not key.lower().startswith("x-google-")
        assert not key.lower().startswith("x-gmail-")
        assert not key.lower().startswith("x-gm-")
    assert msg["Message-ID"] != "<orig-plain@mail.gmail.com>"
    assert PRIVATE not in str(msg["Message-ID"])


def test_html_only_converts_to_plain_without_remote_content() -> None:
    msg = _rebuild("html_only.eml")
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "no plain-text part" in body
    assert "<p>" not in body
    assert "tracker.example" not in body
    assert "evil.example" not in body
    assert msg.get_body(preferencelist=("html",)) is None or msg.get_content_type() == "text/plain"


def test_reply_keeps_newest_content_only() -> None:
    msg = _rebuild("reply_quoted.eml")
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Tuesday afternoon works" in body
    assert "visit campus next week" not in body
    assert msg["Subject"] == "Campus visit"


def test_forwarded_history_is_stripped_when_intro_exists() -> None:
    msg = _rebuild("forwarded_history.eml")
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "submitted the form" in body
    assert "ancient history" not in body
    assert "Begin forwarded message" not in body


def test_private_address_cannot_remain_anywhere() -> None:
    msg = _rebuild("address_leak.eml")
    serialized = msg.as_string()
    assert PRIVATE.lower() not in serialized.lower()
    assert "private.user" not in serialized.lower()
    assert msg["Reply-To"] == PROTON_REPLY_TO
    assert msg["From"] == PROTON_FROM


def test_attachments_copied_as_new_parts_not_original_eml() -> None:
    msg = _rebuild("multiple_attachments.eml")
    filenames = []
    for part in msg.iter_attachments():
        filenames.append(part.get_filename())
        assert part.get_content_type() != "message/rfc822"
    assert "cv.pdf" in filenames
    assert any(name and name.startswith("cv") and name.endswith(".pdf") for name in filenames)
    leaked = [n for n in filenames if n and "gmail.com" in n.lower()]
    assert leaked == []
    assert all(n is None or "xlsm" not in n.lower() for n in filenames)
    serialized = msg.as_bytes()
    assert b"Content-Type: message/rfc822" not in serialized
    assert PRIVATE.encode() not in serialized.lower()


def test_malformed_message_still_yields_body() -> None:
    msg = _rebuild("malformed.eml")
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Still recoverable body" in body


def test_message_id_is_deterministic_and_omits_gmail() -> None:
    a = _rebuild("plain_text.eml", gmail_msgid="999")
    b = _rebuild("plain_text.eml", gmail_msgid="999")
    c = _rebuild("plain_text.eml", gmail_msgid="1000")
    assert a["Message-ID"] == b["Message-ID"]
    assert a["Message-ID"] != c["Message-ID"]
    assert PRIVATE not in a["Message-ID"]
    assert "gmail" not in a["Message-ID"].lower()


def test_colleagues_are_not_placed_in_visible_headers() -> None:
    msg = _rebuild("plain_text.eml")
    serialized = msg.as_string().lower()
    for addr in COLLEAGUES:
        assert addr.lower() not in serialized
    assert msg["Bcc"] is None
    assert msg["Cc"] is None or PRIVATE not in str(msg["Cc"])


def test_original_eml_is_never_attached() -> None:
    msg = _rebuild("plain_text.eml")
    for part in msg.walk():
        assert part.get_content_type() != "message/rfc822"
        filename = part.get_filename() or ""
        assert not filename.endswith(".eml")
