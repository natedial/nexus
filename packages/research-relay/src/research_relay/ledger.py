from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

STATUS_SMTP_ACCEPTED = "smtp_accepted"
STATUS_LABELS_UPDATED = "labels_updated"
STATUS_TEMP_FAILURE = "temp_failure"
STATUS_PERMANENT_ERROR = "permanent_error"

_ERROR_MAX = 500


@dataclass
class LedgerRow:
    gmail_msgid: str
    status: str
    failure_count: int
    last_error: str
    next_retry_at: str | None
    smtp_accepted_at: str | None
    labels_updated_at: str | None


@dataclass
class ArchiveRow:
    gmail_msgid: str
    message_id: str
    kind: str
    expected_names: list[str]
    pdf_ids: dict[str, str]
    doc_ids: dict[str, str]
    html_id: str
    last_error: str
    find_failures: int
    unrecoverable: bool
    enqueued_at: str
    updated_at: str
    content_hash: str = ""
    intake_bundle_id: str = ""
    intake_written_at: str = ""


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._init()

    def _init(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS deliveries (
                gmail_msgid TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                smtp_accepted_at TEXT,
                labels_updated_at TEXT,
                last_error TEXT,
                failure_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS send_counts (
                day TEXT PRIMARY KEY,
                sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relay_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archives (
                gmail_msgid TEXT PRIMARY KEY,
                message_id TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                expected_names TEXT NOT NULL DEFAULT '[]',
                pdf_ids TEXT NOT NULL DEFAULT '{}',
                doc_ids TEXT NOT NULL DEFAULT '{}',
                html_id TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '',
                find_failures INTEGER NOT NULL DEFAULT 0,
                unrecoverable INTEGER NOT NULL DEFAULT 0,
                enqueued_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._migrate_archives_columns()
        self._conn.commit()

    def _migrate_archives_columns(self) -> None:
        for ddl in (
            "ALTER TABLE archives ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE archives ADD COLUMN intake_bundle_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE archives ADD COLUMN intake_written_at TEXT NOT NULL DEFAULT ''",
        ):
            try:
                self._conn.execute(ddl)
            except sqlite3.OperationalError:
                pass

    def enqueue_archive(
        self,
        gmail_msgid: str,
        *,
        message_id: str,
        kind: str,
        expected_names: list[str],
    ) -> ArchiveRow:
        now = _now()
        existing = self.get_archive(gmail_msgid)
        names = json.dumps(list(expected_names))
        mid = (message_id or "").strip()
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO archives (
                    gmail_msgid, message_id, kind, expected_names,
                    pdf_ids, doc_ids, html_id, last_error, find_failures,
                    unrecoverable, enqueued_at, updated_at
                ) VALUES (?, ?, ?, ?, '{}', '{}', '', '', 0, 0, ?, ?)
                """,
                (str(gmail_msgid), mid, kind, names, now, now),
            )
        else:
            self._conn.execute(
                """
                UPDATE archives SET
                    message_id = CASE WHEN ? != '' THEN ? ELSE message_id END,
                    kind = ?,
                    expected_names = ?,
                    updated_at = ?
                WHERE gmail_msgid = ?
                """,
                (mid, mid, kind, names, now, str(gmail_msgid)),
            )
        self._conn.commit()
        row = self.get_archive(gmail_msgid)
        assert row is not None
        return row

    def get_archive(self, gmail_msgid: str) -> ArchiveRow | None:
        row = self._conn.execute(
            """
            SELECT gmail_msgid, message_id, kind, expected_names, pdf_ids, doc_ids,
                   html_id, last_error, find_failures, unrecoverable, enqueued_at, updated_at,
                   content_hash, intake_bundle_id, intake_written_at
            FROM archives WHERE gmail_msgid = ?
            """,
            (str(gmail_msgid),),
        ).fetchone()
        if row is None:
            return None
        return _archive_row(row)

    def list_incomplete(self, limit: int = 20) -> list[ArchiveRow]:
        rows = self._conn.execute(
            """
            SELECT gmail_msgid, message_id, kind, expected_names, pdf_ids, doc_ids,
                   html_id, last_error, find_failures, unrecoverable, enqueued_at, updated_at,
                   content_hash, intake_bundle_id, intake_written_at
            FROM archives WHERE unrecoverable = 0 ORDER BY enqueued_at ASC
            """
        ).fetchall()
        out = [_archive_row(item) for item in rows]
        incomplete = [item for item in out if not self.archive_is_complete(item)]
        return incomplete[: max(0, int(limit))]

    def archive_is_complete(self, row: ArchiveRow | None) -> bool:
        if row is None or row.unrecoverable:
            return False
        if row.kind == "html":
            return bool(row.html_id)
        if not row.expected_names:
            return False
        for name in row.expected_names:
            if not row.pdf_ids.get(name) or not row.doc_ids.get(name):
                return False
        return True

    def record_pdf_id(self, gmail_msgid: str, name: str, drive_id: str) -> None:
        self._merge_archive_map(gmail_msgid, "pdf_ids", name, drive_id)

    def record_doc_id(self, gmail_msgid: str, name: str, drive_id: str) -> None:
        self._merge_archive_map(gmail_msgid, "doc_ids", name, drive_id)

    def record_html_id(self, gmail_msgid: str, drive_id: str) -> None:
        now = _now()
        self._conn.execute(
            "UPDATE archives SET html_id = ?, last_error = '', updated_at = ? WHERE gmail_msgid = ?",
            (drive_id, now, str(gmail_msgid)),
        )
        self._conn.commit()

    def mark_intake_written(
        self, gmail_msgid: str, content_hash: str, bundle_id: str
    ) -> None:
        now = _now()
        self._conn.execute(
            """
            UPDATE archives SET
                content_hash = ?, intake_bundle_id = ?, intake_written_at = ?, updated_at = ?
            WHERE gmail_msgid = ?
            """,
            (content_hash, bundle_id, now, now, str(gmail_msgid)),
        )
        self._conn.commit()

    def record_archive_error(self, gmail_msgid: str, error: str) -> None:
        now = _now()
        self._conn.execute(
            "UPDATE archives SET last_error = ?, updated_at = ? WHERE gmail_msgid = ?",
            (_clip(error), now, str(gmail_msgid)),
        )
        self._conn.commit()

    def record_find_miss(self, gmail_msgid: str, *, threshold: int) -> bool:
        row = self.get_archive(gmail_msgid)
        if row is None:
            return False
        count = row.find_failures + 1
        unrecoverable = 1 if count >= max(1, int(threshold)) else 0
        now = _now()
        self._conn.execute(
            """
            UPDATE archives SET find_failures = ?, unrecoverable = ?, last_error = ?, updated_at = ?
            WHERE gmail_msgid = ?
            """,
            (count, unrecoverable, _clip("imap message-id not found"), now, str(gmail_msgid)),
        )
        self._conn.commit()
        return bool(unrecoverable)

    def clear_archive_ids(self, gmail_msgid: str) -> None:
        now = _now()
        self._conn.execute(
            """
            UPDATE archives SET
                pdf_ids = '{}', doc_ids = '{}', html_id = '',
                unrecoverable = 0, find_failures = 0, last_error = '', updated_at = ?
            WHERE gmail_msgid = ?
            """,
            (now, str(gmail_msgid)),
        )
        self._conn.commit()

    def count_unrecoverable(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM archives WHERE unrecoverable = 1"
        ).fetchone()
        return int(row[0] if row else 0)

    def list_unrecoverable(self) -> list[ArchiveRow]:
        rows = self._conn.execute(
            """
            SELECT gmail_msgid, message_id, kind, expected_names, pdf_ids, doc_ids,
                   html_id, last_error, find_failures, unrecoverable, enqueued_at, updated_at,
                   content_hash, intake_bundle_id, intake_written_at
            FROM archives WHERE unrecoverable = 1 ORDER BY enqueued_at ASC
            """
        ).fetchall()
        return [_archive_row(item) for item in rows]

    def stale_incomplete(
        self,
        *,
        max_age: timedelta,
        now: datetime | None = None,
    ) -> list[ArchiveRow]:
        current = now or datetime.now(timezone.utc)
        cutoff = current - max_age
        stale: list[ArchiveRow] = []
        for row in self.list_incomplete(limit=10_000):
            stamp = row.updated_at or row.enqueued_at
            parsed = _parse_iso(stamp)
            if parsed is not None and parsed <= cutoff:
                stale.append(row)
        return stale

    def _merge_archive_map(self, gmail_msgid: str, column: str, name: str, drive_id: str) -> None:
        row = self.get_archive(gmail_msgid)
        if row is None:
            return
        data = dict(row.pdf_ids if column == "pdf_ids" else row.doc_ids)
        data[name] = drive_id
        now = _now()
        self._conn.execute(
            f"UPDATE archives SET {column} = ?, last_error = '', updated_at = ? WHERE gmail_msgid = ?",
            (json.dumps(data), now, str(gmail_msgid)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, gmail_msgid: str) -> LedgerRow | None:
        row = self._conn.execute(
            "SELECT gmail_msgid, status, failure_count, last_error, next_retry_at, "
            "smtp_accepted_at, labels_updated_at FROM deliveries WHERE gmail_msgid = ?",
            (str(gmail_msgid),),
        ).fetchone()
        if row is None:
            return None
        return LedgerRow(*row)

    def smtp_already_accepted(self, gmail_msgid: str) -> bool:
        row = self.get(gmail_msgid)
        return bool(row and row.status in {STATUS_SMTP_ACCEPTED, STATUS_LABELS_UPDATED})

    def labels_already_updated(self, gmail_msgid: str) -> bool:
        row = self.get(gmail_msgid)
        return bool(row and row.status == STATUS_LABELS_UPDATED)

    def ready_for_retry(self, gmail_msgid: str, now: datetime | None = None) -> bool:
        row = self.get(gmail_msgid)
        if row is None:
            return True
        if row.status in {STATUS_SMTP_ACCEPTED, STATUS_LABELS_UPDATED, STATUS_PERMANENT_ERROR}:
            return False
        if not row.next_retry_at:
            return True
        current = now or datetime.now(timezone.utc)
        try:
            scheduled = datetime.fromisoformat(row.next_retry_at)
        except ValueError:
            return True
        return current >= scheduled

    def record_smtp_accepted(self, gmail_msgid: str) -> None:
        now = _now()
        self._upsert(
            gmail_msgid,
            status=STATUS_SMTP_ACCEPTED,
            smtp_accepted_at=now,
            updated_at=now,
            last_error="",
            next_retry_at=None,
        )

    def record_labels_updated(self, gmail_msgid: str) -> None:
        now = _now()
        self._upsert(
            gmail_msgid,
            status=STATUS_LABELS_UPDATED,
            labels_updated_at=now,
            updated_at=now,
            last_error="",
            next_retry_at=None,
        )

    def record_temp_failure(self, gmail_msgid: str, error: str, backoff_seconds: int) -> None:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        existing = self.get(gmail_msgid)
        count = (existing.failure_count if existing else 0) + 1
        nxt = (now_dt + timedelta(seconds=max(0, backoff_seconds))).isoformat()
        self._upsert(
            gmail_msgid,
            status=STATUS_TEMP_FAILURE,
            last_error=_clip(error),
            failure_count=count,
            next_retry_at=nxt,
            updated_at=now,
        )

    def sent_today(self, day: date | None = None) -> int:
        key = (day or date.today()).isoformat()
        row = self._conn.execute("SELECT sent FROM send_counts WHERE day = ?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def record_send(self, day: date | None = None) -> int:
        key = (day or date.today()).isoformat()
        self._conn.execute(
            """
            INSERT INTO send_counts (day, sent) VALUES (?, 1)
            ON CONFLICT(day) DO UPDATE SET sent = sent + 1
            """,
            (key,),
        )
        self._conn.commit()
        return self.sent_today(date.fromisoformat(key))

    def circuit_is_open(self) -> bool:
        return self._state("circuit_open") == "1"

    def circuit_reason(self) -> str:
        return self._state("circuit_reason")

    def trip_circuit(self, reason: str) -> None:
        self._set_state("circuit_open", "1")
        self._set_state("circuit_reason", (reason or "").strip())

    def reset_circuit(self) -> None:
        self._set_state("circuit_open", "0")
        self._set_state("circuit_reason", "")

    def alert_status(self) -> str:
        return self._state("alert_status")

    def alert_kind(self) -> str:
        return self._state("alert_kind")

    def alert_sent_at(self) -> datetime | None:
        raw = self._state("alert_sent_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def record_alert(self, status: str, kind: str, sent_at: datetime) -> None:
        self._set_state("alert_status", status)
        self._set_state("alert_kind", kind)
        self._set_state("alert_sent_at", sent_at.isoformat())

    def _state(self, key: str) -> str:
        row = self._conn.execute("SELECT value FROM relay_state WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def _set_state(self, key: str, value: str) -> None:
        now = _now()
        self._conn.execute(
            """
            INSERT INTO relay_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self._conn.commit()

    def record_permanent_error(self, gmail_msgid: str, error: str) -> None:
        now = _now()
        existing = self.get(gmail_msgid)
        count = (existing.failure_count if existing else 0) + 1
        self._upsert(
            gmail_msgid,
            status=STATUS_PERMANENT_ERROR,
            last_error=_clip(error),
            failure_count=count,
            next_retry_at=None,
            updated_at=now,
        )

    def _upsert(
        self,
        gmail_msgid: str,
        *,
        status: str,
        updated_at: str,
        last_error: str | None = None,
        failure_count: int | None = None,
        next_retry_at: str | None = None,
        smtp_accepted_at: str | None = None,
        labels_updated_at: str | None = None,
    ) -> None:
        existing = self.get(gmail_msgid)
        created = existing.created_at if existing and getattr(existing, "created_at", None) else updated_at
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO deliveries (
                    gmail_msgid, status, smtp_accepted_at, labels_updated_at, last_error,
                    failure_count, next_retry_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(gmail_msgid),
                    status,
                    smtp_accepted_at,
                    labels_updated_at,
                    last_error or "",
                    failure_count or 0,
                    next_retry_at,
                    updated_at,
                    updated_at,
                ),
            )
        else:
            self._conn.execute(
                """
                UPDATE deliveries SET
                    status = ?,
                    smtp_accepted_at = COALESCE(?, smtp_accepted_at),
                    labels_updated_at = COALESCE(?, labels_updated_at),
                    last_error = ?,
                    failure_count = ?,
                    next_retry_at = ?,
                    updated_at = ?
                WHERE gmail_msgid = ?
                """,
                (
                    status,
                    smtp_accepted_at,
                    labels_updated_at,
                    last_error if last_error is not None else existing.last_error,
                    failure_count if failure_count is not None else existing.failure_count,
                    next_retry_at,
                    updated_at,
                    str(gmail_msgid),
                ),
            )
        self._conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(error: str) -> str:
    text = (error or "").replace("\n", " ").strip()
    if len(text) > _ERROR_MAX:
        return text[:_ERROR_MAX] + "…"
    return text


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _archive_row(row: tuple) -> ArchiveRow:
    return ArchiveRow(
        gmail_msgid=str(row[0]),
        message_id=str(row[1] or ""),
        kind=str(row[2]),
        expected_names=list(json.loads(row[3] or "[]")),
        pdf_ids=dict(json.loads(row[4] or "{}")),
        doc_ids=dict(json.loads(row[5] or "{}")),
        html_id=str(row[6] or ""),
        last_error=str(row[7] or ""),
        find_failures=int(row[8] or 0),
        unrecoverable=bool(row[9]),
        enqueued_at=str(row[10]),
        updated_at=str(row[11]),
        content_hash=str(row[12] or "") if len(row) > 12 else "",
        intake_bundle_id=str(row[13] or "") if len(row) > 13 else "",
        intake_written_at=str(row[14] or "") if len(row) > 14 else "",
    )
