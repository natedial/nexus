from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime


def gmail_pending_query(base_query: str, max_age_days: int) -> str:
    query = (base_query or "").strip()
    days = int(max_age_days or 0)
    if days <= 0:
        return query
    token = f"newer_than:{days}d"
    if token in query:
        return query
    return f"{query} {token}".strip()


def header_is_fresh(header: bytes, max_age_days: int, *, now: datetime | None = None) -> bool:
    days = int(max_age_days or 0)
    if days <= 0:
        return True
    parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
    raw = parsed.get("Date")
    if not raw:
        return False
    try:
        stamp = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return stamp >= moment - timedelta(days=days)


def header_is_within(header: bytes, max_age: timedelta, *, now: datetime | None = None) -> bool:
    parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
    raw = parsed.get("Date")
    if not raw:
        return False
    try:
        stamp = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return stamp >= moment - max_age


def header_is_on_or_after(header: bytes, cutoff: datetime) -> bool:
    parsed = BytesParser(policy=policy.default).parsebytes(header or b"")
    raw = parsed.get("Date")
    if not raw:
        return False
    try:
        stamp = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    when = cutoff
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return stamp >= when


def parse_since_day(text: str) -> datetime:
    raw = (text or "").strip()
    try:
        day = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("since date must be YYYY-MM-DD") from exc
    local = datetime.now().astimezone()
    return day.replace(tzinfo=local.tzinfo)


_IMAP_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def imap_since_date(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return f"{when.day}-{_IMAP_MONTHS[when.month - 1]}-{when.year}"
