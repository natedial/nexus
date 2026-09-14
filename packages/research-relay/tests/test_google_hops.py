from research_relay.google_hops import has_google_hops


def test_detects_gmail_transport_headers() -> None:
    raw = (
        b"From: a@candidates.edu\r\n"
        b"Received: from mail-yw1.google.com (mail-yw1.google.com [1.2.3.4])\r\n"
        b"Message-ID: <x@mail.gmail.com>\r\n\r\nbody\r\n"
    )
    assert has_google_hops(raw) is True


def test_detects_x_google_header() -> None:
    raw = b"From: a@x.edu\r\nX-Google-Smtp-Source: ABC\r\n\r\nhi\r\n"
    assert has_google_hops(raw) is True


def test_proton_internal_has_no_google_hops() -> None:
    raw = (
        b"From: Macro Insights <MacroRates@proton.me>\r\n"
        b"Message-ID: <abc=@proton.me>\r\n"
        b"Date: Mon, 17 Aug 2026 17:51:02 +0000\r\n\r\n"
        b"encrypted-looking body\r\n"
    )
    assert has_google_hops(raw) is False
