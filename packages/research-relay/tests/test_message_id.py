from research_relay.message_id import make_message_id


def test_deterministic_for_same_gmail_msgid() -> None:
    key = b"secret-hmac"
    assert make_message_id("111", key, "relay.local") == make_message_id(
        "111", key, "relay.local"
    )


def test_changes_when_gmail_msgid_changes() -> None:
    key = b"secret-hmac"
    assert make_message_id("111", key, "relay.local") != make_message_id(
        "112", key, "relay.local"
    )


def test_does_not_embed_gmail_address_or_msgid_plaintext() -> None:
    mid = make_message_id("999888777", b"key", "relay.local")
    assert "gmail" not in mid.lower()
    assert "999888777" not in mid
    assert mid.startswith("<")
    assert mid.endswith("@relay.local>")
