from research_relay.redact import redact_text, redact_filename


PRIVATE = "private.user@gmail.com"


def test_redacts_case_insensitive_address_in_subject() -> None:
    text = "Hello PRIVATE.USER@GMAIL.COM please read"
    assert PRIVATE.lower() not in redact_text(text, PRIVATE).lower()
    assert "[redacted]" in redact_text(text, PRIVATE)


def test_redacts_address_in_body() -> None:
    body = f"Contact me at {PRIVATE} or call."
    out = redact_text(body, PRIVATE)
    assert PRIVATE not in out
    assert "Contact me at [redacted] or call." == out


def test_redacts_html_entity_encoded_at_sign() -> None:
    text = "private.user&#64;gmail.com and private.user&#x40;gmail.com"
    out = redact_text(text, PRIVATE)
    assert "gmail.com" not in out.lower() or "private.user" not in out.lower()
    assert "[redacted]" in out


def test_redacts_url_encoded_address() -> None:
    text = "mailto:private.user%40gmail.com"
    out = redact_text(text, PRIVATE)
    assert "%40gmail.com" not in out.lower()
    assert "private.user" not in out.lower()


def test_redacts_filename() -> None:
    name = "notes-for-private.user@gmail.com.pdf"
    out = redact_filename(name, PRIVATE)
    assert "gmail.com" not in out.lower()
    assert "/" not in out
    assert ".." not in out


def test_leaves_unrelated_addresses_intact() -> None:
    text = "From alice@candidates.edu to colleague@proton.me"
    assert redact_text(text, PRIVATE) == text
