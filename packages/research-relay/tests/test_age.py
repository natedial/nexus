from datetime import datetime, timedelta, timezone

from research_relay.age import (
    gmail_pending_query,
    header_is_fresh,
    header_is_on_or_after,
    header_is_within,
    imap_since_date,
    parse_since_day,
)


def test_gmail_query_appends_newer_than() -> None:
    query = gmail_pending_query("label:relay/pending", 5)
    assert query.endswith("newer_than:5d")
    assert gmail_pending_query(query, 5) == query
    assert gmail_pending_query("label:relay/pending", 0) == "label:relay/pending"


def test_header_is_fresh_uses_date() -> None:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    fresh = b"Date: Mon, 17 Aug 2026 10:00:00 +0000\r\n\r\n"
    stale = b"Date: Fri, 01 Aug 2026 10:00:00 +0000\r\n\r\n"
    assert header_is_fresh(fresh, 5, now=now) is True
    assert header_is_fresh(stale, 5, now=now) is False
    assert header_is_fresh(b"\r\n", 5, now=now) is False
    assert header_is_fresh(stale, 0, now=now) is True


def test_header_is_within_hours() -> None:
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    recent = b"Date: Thu, 27 Aug 2026 15:00:00 +0000\r\n\r\n"
    old = b"Date: Tue, 25 Aug 2026 10:00:00 +0000\r\n\r\n"
    window = timedelta(hours=48)
    assert header_is_within(recent, window, now=now) is True
    assert header_is_within(old, window, now=now) is False
    assert header_is_within(b"\r\n", window, now=now) is False


def test_imap_since_date_is_imap_english() -> None:
    stamp = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)
    assert imap_since_date(stamp) == "26-Aug-2026"


def test_header_is_on_or_after_cutoff() -> None:
    cutoff = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)
    on_day = b"Date: Sat, 15 Aug 2026 00:00:00 +0000\r\n\r\n"
    later = b"Date: Sun, 16 Aug 2026 10:00:00 +0000\r\n\r\n"
    earlier = b"Date: Fri, 14 Aug 2026 23:59:59 +0000\r\n\r\n"
    assert header_is_on_or_after(on_day, cutoff) is True
    assert header_is_on_or_after(later, cutoff) is True
    assert header_is_on_or_after(earlier, cutoff) is False


def test_parse_since_day_is_local_midnight() -> None:
    stamp = parse_since_day("2026-08-15")
    assert stamp.year == 2026
    assert stamp.month == 8
    assert stamp.day == 15
    assert stamp.hour == 0
    assert stamp.tzinfo is not None
