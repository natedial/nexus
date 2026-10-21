from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_gleaner.models import CapturedExcerpt

DELIVERY_STATUSES = frozenset({"pending", "delivered", "failed", "skipped"})


class CaptureStore:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            columns = _table_columns(connection, "captures")
            if columns and "category" in columns:
                self._migrate_v1(connection)
            self._create_schema(connection)

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_documents (
                source_kind TEXT NOT NULL,
                document_id TEXT NOT NULL,
                uri TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT,
                file_type TEXT,
                remote_modified_at TEXT,
                processed_revision TEXT,
                last_seen_at TEXT NOT NULL,
                last_processed_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (source_kind, document_id)
            );

            CREATE INDEX IF NOT EXISTS idx_source_documents_revision
                ON source_documents(source_kind, processed_revision);

            CREATE TABLE IF NOT EXISTS captures (
                capture_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                source_kind TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_title TEXT NOT NULL,
                document_uri TEXT NOT NULL,
                document_modified_at TEXT,
                source_style TEXT NOT NULL,
                intent TEXT NOT NULL,
                text TEXT NOT NULL,
                context_text TEXT NOT NULL,
                page_number INTEGER,
                active INTEGER NOT NULL DEFAULT 1,
                payload_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_captures_document
                ON captures(source_kind, document_id);
            CREATE INDEX IF NOT EXISTS idx_captures_intent
                ON captures(intent);
            CREATE INDEX IF NOT EXISTS idx_captures_source_style
                ON captures(source_style);
            CREATE INDEX IF NOT EXISTS idx_captures_first_seen
                ON captures(first_seen_at);
            CREATE INDEX IF NOT EXISTS idx_captures_active
                ON captures(active);

            CREATE TABLE IF NOT EXISTS deliveries (
                capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
                destination TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (capture_id, destination)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
                capture_id UNINDEXED,
                document_title,
                text,
                context_text,
                source_style
            );
            """
        )

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT * FROM captures").fetchall()
        deliveries = connection.execute("SELECT * FROM deliveries").fetchall()
        connection.execute("DROP TABLE deliveries")
        connection.execute("ALTER TABLE captures RENAME TO captures_v1")
        self._create_schema(connection)
        id_map: dict[str, str] = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload.pop("category", None)
            source_style = str(payload.get("source_style") or "unknown").strip().lower()
            payload["source_style"] = source_style
            payload["schema_version"] = 2
            document = payload.get("document") or {}
            locator = payload.get("locator") or {}
            capture_id = _v2_capture_id(payload)
            payload["capture_id"] = capture_id
            id_map[row["capture_id"]] = capture_id
            connection.execute(
                """
                INSERT OR IGNORE INTO captures (
                    capture_id, schema_version, source_kind, document_id,
                    document_title, document_uri, document_modified_at,
                    source_style, intent, text, context_text, page_number,
                    payload_json, first_seen_at, last_seen_at, seen_count
                ) VALUES (?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    row["source_kind"],
                    row["document_id"],
                    document.get("title") or "Untitled",
                    document.get("uri") or "",
                    document.get("modified_at"),
                    source_style,
                    row["intent"],
                    payload.get("text") or "",
                    payload.get("context_text") or "",
                    locator.get("page_number"),
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    row["first_seen_at"],
                    row["last_seen_at"],
                    row["seen_count"],
                ),
            )
        for delivery in deliveries:
            capture_id = id_map.get(delivery["capture_id"])
            if capture_id is None:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO deliveries (
                    capture_id, destination, status, attempts, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    delivery["destination"],
                    delivery["status"],
                    delivery["attempts"],
                    delivery["last_error"],
                    delivery["updated_at"],
                ),
            )
        connection.execute("DROP TABLE captures_v1")
        self._create_schema(connection)
        self._rebuild_fts(connection)

    def register(self, capture: CapturedExcerpt) -> bool:
        return bool(self.register_many([capture]))

    def register_many(self, captures: Iterable[CapturedExcerpt]) -> list[str]:
        new_ids: list[str] = []
        now = _now_iso()
        with self._connect() as connection:
            for capture in captures:
                payload = json.dumps(capture.to_dict(), sort_keys=True, separators=(",", ":"))
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO captures (
                        capture_id, schema_version, source_kind, document_id,
                        document_title, document_uri, document_modified_at,
                        source_style, intent, text, context_text, page_number,
                        payload_json, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture.capture_id,
                        capture.schema_version,
                        capture.document.source_kind,
                        capture.document.document_id,
                        capture.document.title,
                        capture.document.uri,
                        _iso(capture.document.modified_at),
                        capture.source_style,
                        capture.intent.value,
                        capture.text,
                        capture.context_text,
                        capture.locator.page_number,
                        payload,
                        now,
                        now,
                    ),
                )
                if cursor.rowcount == 1:
                    new_ids.append(capture.capture_id)
                else:
                    connection.execute(
                        """
                        UPDATE captures
                        SET payload_json = ?, intent = ?, source_style = ?, text = ?,
                            context_text = ?, page_number = ?, active = 1,
                            last_seen_at = ?, seen_count = seen_count + 1
                        WHERE capture_id = ?
                        """,
                        (
                            payload,
                            capture.intent.value,
                            capture.source_style,
                            capture.text,
                            capture.context_text,
                            capture.locator.page_number,
                            now,
                            capture.capture_id,
                        ),
                    )
                self._index_capture(connection, capture)
        return new_ids

    def record_document(
        self,
        *,
        source_kind: str,
        document_id: str,
        uri: str,
        title: str,
        path: str | None = None,
        file_type: str | None = None,
        remote_modified_at: str | None = None,
        processed_revision: str | None = None,
        metadata: dict[str, Any] | None = None,
        processed: bool = False,
    ) -> None:
        now = _now_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO source_documents (
                    source_kind, document_id, uri, title, path, file_type,
                    remote_modified_at, processed_revision, last_seen_at,
                    last_processed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_kind, document_id) DO UPDATE SET
                    uri = excluded.uri,
                    title = excluded.title,
                    path = excluded.path,
                    file_type = COALESCE(excluded.file_type, source_documents.file_type),
                    remote_modified_at = excluded.remote_modified_at,
                    processed_revision = COALESCE(
                        excluded.processed_revision, source_documents.processed_revision
                    ),
                    last_seen_at = excluded.last_seen_at,
                    last_processed_at = COALESCE(
                        excluded.last_processed_at, source_documents.last_processed_at
                    ),
                    metadata_json = excluded.metadata_json
                """,
                (
                    source_kind,
                    document_id,
                    uri,
                    title,
                    path,
                    file_type,
                    remote_modified_at,
                    processed_revision,
                    now,
                    now if processed else None,
                    json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                ),
            )

    def processed_revision(self, source_kind: str, document_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT processed_revision FROM source_documents
                WHERE source_kind = ? AND document_id = ?
                """,
                (source_kind, document_id),
            ).fetchone()
        return str(row["processed_revision"]) if row and row["processed_revision"] else None

    def reconcile_document(
        self,
        source_kind: str,
        document_id: str,
        active_capture_ids: Iterable[str],
    ) -> None:
        active_ids = tuple(active_capture_ids)
        with self._connect() as connection:
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                connection.execute(
                    f"""
                    UPDATE captures SET active = 0
                    WHERE source_kind = ? AND document_id = ?
                      AND capture_id NOT IN ({placeholders})
                    """,
                    (source_kind, document_id, *active_ids),
                )
            else:
                connection.execute(
                    "UPDATE captures SET active = 0 WHERE source_kind = ? AND document_id = ?",
                    (source_kind, document_id),
                )

    def search(
        self,
        *,
        text: str | None = None,
        source_kind: str | None = None,
        source_style: str | None = None,
        intent: str | None = None,
        document: str | None = None,
        first_seen_since: datetime | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        join = ""
        if text:
            join = "JOIN captures_fts fts ON fts.capture_id = captures.capture_id"
            clauses.append("captures_fts MATCH ?")
            parameters.append(_fts_query(text))
        if source_kind:
            clauses.append("captures.source_kind = ?")
            parameters.append(source_kind.strip().lower())
        if source_style:
            clauses.append("captures.source_style = ?")
            parameters.append(source_style.strip().lower())
        if intent:
            clauses.append("captures.intent = ?")
            parameters.append(intent.strip().lower())
        if document:
            clauses.append("captures.document_title LIKE ? ESCAPE '\\'")
            parameters.append(f"%{_escape_like(document)}%")
        if first_seen_since:
            clauses.append("captures.first_seen_at >= ?")
            parameters.append(_iso(first_seen_since))
        if active_only:
            clauses.append("captures.active = 1")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(max(1, min(limit, 500)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT captures.* FROM captures {join}{where}
                ORDER BY captures.first_seen_at DESC, captures.capture_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [_row_result(row) for row in rows]

    def mark_delivery(
        self,
        capture_id: str,
        destination: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        if status not in DELIVERY_STATUSES:
            raise ValueError(f"invalid delivery status: {status}")
        destination = destination.strip().lower()
        if not destination:
            raise ValueError("destination must not be empty")
        attempts_increment = 1 if status in {"delivered", "failed"} else 0
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM captures WHERE capture_id = ?", (capture_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(capture_id)
            connection.execute(
                """
                INSERT INTO deliveries (
                    capture_id, destination, status, attempts, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id, destination) DO UPDATE SET
                    status = excluded.status,
                    attempts = deliveries.attempts + excluded.attempts,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    capture_id,
                    destination,
                    status,
                    attempts_increment,
                    error,
                    _now_iso(),
                ),
            )

    def get(self, capture_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM captures WHERE capture_id = ?", (capture_id,)
            ).fetchone()
        return _row_result(row) if row else None

    def delivery(self, capture_id: str, destination: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM deliveries
                WHERE capture_id = ? AND destination = ?
                """,
                (capture_id, destination.strip().lower()),
            ).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM captures").fetchone()
        return int(row["count"])

    def _index_capture(self, connection: sqlite3.Connection, capture: CapturedExcerpt) -> None:
        connection.execute("DELETE FROM captures_fts WHERE capture_id = ?", (capture.capture_id,))
        connection.execute(
            """
            INSERT INTO captures_fts (
                capture_id, document_title, text, context_text, source_style
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                capture.capture_id,
                capture.document.title,
                capture.text,
                capture.context_text,
                capture.source_style,
            ),
        )

    def _rebuild_fts(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM captures_fts")
        connection.execute(
            """
            INSERT INTO captures_fts (
                capture_id, document_title, text, context_text, source_style
            )
            SELECT capture_id, document_title, text, context_text, source_style
            FROM captures
            """
        )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _v2_capture_id(payload: dict[str, Any]) -> str:
    identity = {
        "version": 2,
        "source_kind": str((payload.get("document") or {}).get("source_kind") or "").lower(),
        "document_id": str((payload.get("document") or {}).get("document_id") or ""),
        "locator": payload.get("locator") or {},
        "source_style": str(payload.get("source_style") or "unknown").lower(),
        "text": str(payload.get("text") or ""),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "cap_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_result(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["active"] = bool(result["active"])
    result["payload"] = json.loads(result.pop("payload_json"))
    return result


def _fts_query(value: str) -> str:
    terms = re.findall(r"[\w'-]+", value, flags=re.UNICODE)
    if not terms:
        raise ValueError("text query must contain a searchable term")
    return " AND ".join(f'"{term}"' for term in terms)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
