from email.message import EmailMessage

from research_relay.stamp import (
    STAMP_HEADER,
    is_auto_submitted,
    message_is_own_output,
    stamp_token,
    stamp_value,
)


def test_stamp_token_is_stable_for_the_same_key() -> None:
    assert stamp_token(b"unit-key") == stamp_token(b"unit-key")
    assert stamp_token(b"unit-key") != stamp_token(b"other-key")
    assert len(stamp_token(b"unit-key")) == 16


def test_message_is_own_output_matches_header_or_body_token() -> None:
    token = stamp_value(b"unit-key")
    headed = EmailMessage()
    headed["From"] = "alice@candidates.edu"
    headed[STAMP_HEADER] = token
    headed.set_content("hello")
    assert message_is_own_output(headed, b"unit-key")

    bodied = EmailMessage()
    bodied["From"] = "alice@candidates.edu"
    bodied["Message-ID"] = "<rewritten@proton.me>"
    bodied.set_content(f"Sender: Alice <alice@candidates.edu>\n{STAMP_HEADER}: {token}\n\nhello\n")
    assert message_is_own_output(bodied, b"unit-key")
    assert not message_is_own_output(bodied, b"other-key")


def test_auto_submitted_generated_is_own_output_but_no_is_not() -> None:
    generated = EmailMessage()
    generated["From"] = "alice@candidates.edu"
    generated["Auto-Submitted"] = "auto-generated"
    generated.set_content("hello")
    assert is_auto_submitted(generated)
    assert message_is_own_output(generated, b"unit-key")

    human = EmailMessage()
    human["From"] = "alice@candidates.edu"
    human["Auto-Submitted"] = "no"
    human.set_content("hello")
    assert not is_auto_submitted(human)
    assert not message_is_own_output(human, b"unit-key")
