from research_relay.quotes import strip_quoted_history


def test_keeps_content_when_no_separator_present() -> None:
    body = "Please find my CV attached.\nI am available next week."
    assert strip_quoted_history(body) == body


def test_strips_gmail_on_wrote_separator() -> None:
    body = (
        "I can meet on Tuesday.\n"
        "\n"
        "On Mon, Aug 11, 2026 at 9:04 AM PI Name <pi@lab.edu> wrote:\n"
        "> Can you visit campus?\n"
    )
    out = strip_quoted_history(body)
    assert "I can meet on Tuesday." in out
    assert "Can you visit campus?" not in out
    assert "wrote:" not in out


def test_strips_wrapped_gmail_on_wrote() -> None:
    body = (
        "Tuesday works.\n\n"
        "On Mon, Aug 11, 2026 at 9:04 AM PI Name\n"
        "<pi@lab.edu> wrote:\n"
        "> earlier question\n"
    )
    out = strip_quoted_history(body)
    assert "Tuesday works." in out
    assert "earlier question" not in out


def test_strips_outlook_original_message() -> None:
    body = (
        "Thanks, I will send the paper.\n\n"
        "-----Original Message-----\n"
        "From: PI Name\n"
        "Sent: Monday, August 11, 2026 9:04 AM\n"
        "Subject: Paper\n"
    )
    out = strip_quoted_history(body)
    assert "Thanks, I will send the paper." in out
    assert "Original Message" not in out


def test_strips_outlook_underscore_separator() -> None:
    body = "My latest thought.\n\n" + ("_" * 40) + "\nFrom: someone\n"
    out = strip_quoted_history(body)
    assert "My latest thought." in out
    assert "From: someone" not in out


def test_strips_apple_begin_forwarded_message() -> None:
    body = (
        "FYI below is old context I do not need relayed as history.\n\n"
        "Begin forwarded message:\n"
        "From: old@example.com\n"
        "This is historical forwarded content.\n"
    )
    out = strip_quoted_history(body)
    assert "FYI below is old context" in out
    assert "historical forwarded content" not in out


def test_does_not_truncate_when_separator_is_the_entire_payload() -> None:
    body = (
        "-----Original Message-----\n"
        "From: candidate@candidates.edu\n"
        "This is the actual candidate message with no intro.\n"
    )
    out = strip_quoted_history(body)
    assert "actual candidate message" in out


def test_does_not_treat_random_on_wrote_in_prose_as_separator() -> None:
    body = "On Tuesday I wrote a paper about mail systems and quoted history."
    assert strip_quoted_history(body) == body
