from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from research_relay.ledger import STATUS_LABELS_UPDATED, STATUS_SMTP_ACCEPTED, Ledger


def test_records_and_looks_up_by_gmail_msgid(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record_smtp_accepted("42")
    row = ledger.get("42")
    assert row is not None
    assert row.status == STATUS_SMTP_ACCEPTED
    assert ledger.smtp_already_accepted("42")
    assert not ledger.labels_already_updated("42")


def test_label_retry_does_not_look_like_unsent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record_smtp_accepted("7")
    ledger.record_labels_updated("7")
    assert ledger.smtp_already_accepted("7")
    assert ledger.labels_already_updated("7")
    assert ledger.get("7").status == STATUS_LABELS_UPDATED


def test_temporary_failure_keeps_retry_state(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record_temp_failure("9", "smtp timeout", backoff_seconds=30)
    row = ledger.get("9")
    assert row.failure_count == 1
    assert row.last_error == "smtp timeout"
    assert not ledger.smtp_already_accepted("9")
    assert not ledger.ready_for_retry("9")


def test_permanent_error_is_recorded_without_body(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record_permanent_error("3", "sender domain not allowed")
    row = ledger.get("3")
    assert row.status == "permanent_error"
    assert "domain" in row.last_error


def test_error_text_is_truncated(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.record_temp_failure("1", "x" * 5000, backoff_seconds=1)
    assert len(ledger.get("1").last_error) < 1000


def test_daily_send_count_is_local_date_and_increments(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    today = date(2026, 8, 21)
    assert ledger.sent_today(today) == 0
    assert ledger.record_send(today) == 1
    assert ledger.record_send(today) == 2
    assert ledger.sent_today(today) == 2
    assert ledger.sent_today(date(2026, 8, 22)) == 0


def test_circuit_breaker_trips_and_resets(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    assert not ledger.circuit_is_open()
    ledger.trip_circuit("proton pending did not shrink")
    assert ledger.circuit_is_open()
    assert "shrink" in ledger.circuit_reason()
    ledger.reset_circuit()
    assert not ledger.circuit_is_open()
    assert ledger.circuit_reason() == ""


def test_enqueue_archive_is_idempotent_and_keeps_ids(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive(
        "proton:<a@x>",
        message_id="<a@x>",
        kind="pdfs",
        expected_names=["2026-08-28_s_a.pdf"],
    )
    ledger.record_pdf_id("proton:<a@x>", "2026-08-28_s_a.pdf", "pdf1")
    ledger.enqueue_archive(
        "proton:<a@x>",
        message_id="<a@x>",
        kind="pdfs",
        expected_names=["2026-08-28_s_a.pdf"],
    )
    row = ledger.get_archive("proton:<a@x>")
    assert row is not None
    assert row.pdf_ids["2026-08-28_s_a.pdf"] == "pdf1"
    assert not ledger.archive_is_complete(row)


def test_archive_complete_when_pdf_and_doc_ids_present(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive("k", message_id="<m>", kind="pdfs", expected_names=["a.pdf"])
    ledger.record_pdf_id("k", "a.pdf", "p")
    assert not ledger.archive_is_complete(ledger.get_archive("k"))
    ledger.record_doc_id("k", "a.pdf", "d")
    assert ledger.archive_is_complete(ledger.get_archive("k"))
    assert ledger.list_incomplete(limit=10) == []


def test_archive_html_complete_with_html_id(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive("h", message_id="<m>", kind="html", expected_names=[])
    assert ledger.list_incomplete(limit=5)[0].gmail_msgid == "h"
    ledger.record_html_id("h", "html1")
    assert ledger.archive_is_complete(ledger.get_archive("h"))


def test_find_miss_marks_unrecoverable_at_threshold(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive("k", message_id="<m>", kind="html", expected_names=[])
    for _ in range(4):
        assert not ledger.record_find_miss("k", threshold=5)
    assert ledger.record_find_miss("k", threshold=5)
    row = ledger.get_archive("k")
    assert row.unrecoverable is True
    assert row.find_failures == 5
    assert ledger.list_incomplete(limit=10) == []


def test_clear_archive_ids_allows_force_reupload(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive("k", message_id="<m>", kind="pdfs", expected_names=["a.pdf"])
    ledger.record_pdf_id("k", "a.pdf", "p")
    ledger.record_doc_id("k", "a.pdf", "d")
    ledger.clear_archive_ids("k")
    row = ledger.get_archive("k")
    assert row.pdf_ids == {}
    assert row.doc_ids == {}
    assert not ledger.archive_is_complete(row)


def test_stale_incomplete_uses_enqueued_age(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.enqueue_archive("fresh", message_id="<a>", kind="html", expected_names=[])
    ledger.enqueue_archive("old", message_id="<b>", kind="html", expected_names=[])
    old = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc).isoformat()
    ledger._conn.execute(
        "UPDATE archives SET enqueued_at = ?, updated_at = ? WHERE gmail_msgid = ?",
        (old, old, "old"),
    )
    ledger._conn.commit()
    now = datetime(2026, 8, 28, 14, 0, tzinfo=timezone.utc)
    stale = ledger.stale_incomplete(max_age=timedelta(hours=9), now=now)
    assert [row.gmail_msgid for row in stale] == ["old"]
    assert ledger.count_unrecoverable() == 0
