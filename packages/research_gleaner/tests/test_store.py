import json
import sqlite3
from datetime import UTC, datetime, timedelta

from research_gleaner.models import (
    CapturedExcerpt,
    CaptureIntent,
    SourceDocumentRef,
    SourceLocator,
)
from research_gleaner.store import CaptureStore


def capture(
    intent=CaptureIntent.HOLD,
    *,
    text="Idea",
    source_style="blue",
    block_id="block-1",
):
    return CapturedExcerpt.create(
        document=SourceDocumentRef(
            source_kind="notion",
            document_id="page-1",
            uri="https://notion.so/page-1",
            title="Rates",
        ),
        locator=SourceLocator(block_id=block_id, char_start=0, char_end=4),
        text=text,
        context_text=f"{text} in dealer inventory context",
        source_style=source_style,
        intent=intent,
    )


def test_register_is_idempotent_across_runs(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    item = capture()

    assert store.register(item) is True
    assert store.register(item) is False

    row = store.get(item.capture_id)
    assert store.count() == 1
    assert row["seen_count"] == 2


def test_repeat_capture_updates_intent_without_changing_identity(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    held = capture(CaptureIntent.HOLD)
    routed = capture(CaptureIntent.RESEARCH)

    assert held.capture_id == routed.capture_id
    store.register(held)
    store.register(routed)

    row = store.get(held.capture_id)
    assert row["intent"] == "research"
    assert row["payload"]["intent"] == "research"


def test_delivery_status_is_tracked_per_destination(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    item = capture(CaptureIntent.BOTH)
    store.register(item)

    store.mark_delivery(item.capture_id, "research", "failed", error="offline")
    store.mark_delivery(item.capture_id, "research", "delivered")
    store.mark_delivery(item.capture_id, "relay", "pending")

    research = store.delivery(item.capture_id, "research")
    relay = store.delivery(item.capture_id, "relay")
    assert research["status"] == "delivered"
    assert research["attempts"] == 2
    assert relay["status"] == "pending"
    assert relay["attempts"] == 0


def test_search_filters_full_text_style_and_activity(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    pink = capture(text="Dealers moved inventory", source_style="pink", block_id="pink")
    blue = capture(text="Inflation slowed", source_style="blue", block_id="blue")
    store.register_many([pink, blue])

    results = store.search(text="dealer inventory", source_style="pink")
    assert [row["capture_id"] for row in results] == [pink.capture_id]

    store.reconcile_document("notion", "page-1", [blue.capture_id])
    assert store.search(source_style="pink") == []
    assert store.search(source_style="pink", active_only=False)[0]["active"] is False


def test_document_revision_checkpoint_is_recorded(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    store.record_document(
        source_kind="remarkable",
        document_id="doc-1",
        uri="remarkable:///Research.pdf",
        title="Research",
        path="/Research.pdf",
        file_type="pdf",
        remote_modified_at="2026-10-14T10:00:00+00:00",
        processed_revision="revision-1",
        processed=True,
    )

    assert store.processed_revision("remarkable", "doc-1") == "revision-1"


def test_search_can_filter_by_first_seen_time(tmp_path):
    store = CaptureStore(tmp_path / "gleaner.db")
    item = capture()
    store.register(item)

    assert store.search(first_seen_since=datetime.now(UTC) - timedelta(minutes=1))
    assert store.search(first_seen_since=datetime.now(UTC) + timedelta(minutes=1)) == []


def test_v1_database_is_migrated_without_category(tmp_path):
    path = tmp_path / "gleaner.db"
    item = capture()
    payload = item.to_dict()
    payload["schema_version"] = 1
    payload["capture_id"] = "legacy-id"
    payload["category"] = "durable"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE captures (
                capture_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                source_kind TEXT NOT NULL, document_id TEXT NOT NULL,
                category TEXT NOT NULL, intent TEXT NOT NULL, payload_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE deliveries (
                capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
                destination TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT NOT NULL,
                PRIMARY KEY (capture_id, destination)
            );
            """
        )
        connection.execute(
            """
            INSERT INTO captures VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "legacy-id",
                "notion",
                "page-1",
                "durable",
                "hold",
                json.dumps(payload),
                "2026-10-14T00:00:00+00:00",
                "2026-10-14T00:00:00+00:00",
            ),
        )

    store = CaptureStore(path)

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(captures)")}
    assert "category" not in columns
    assert store.count() == 1
    assert store.search(source_style="blue")[0]["payload"].get("category") is None
