from types import SimpleNamespace

import pytest

from scripts.backfill_research_memory_substrate import (
    process_record,
    validate_args,
    validate_no_key_drift,
)
from src.research_memory.backfill import build_backfill_records


class _FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.action = "select"
        self.columns = None
        self.filters = []
        self.payload = None
        self.on_conflict = None

    def select(self, columns):
        self.action = "select"
        self.columns = [column.strip() for column in columns.split(",")]
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def delete(self):
        self.action = "delete"
        return self

    def upsert(self, payload, on_conflict):
        self.action = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self):
        rows = self.client.rows.setdefault(self.name, [])
        matched = [
            row
            for row in rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        if self.action == "delete":
            self.client.rows[self.name] = [
                row
                for row in rows
                if not all(row.get(column) == value for column, value in self.filters)
            ]
            return SimpleNamespace(data=matched)
        if self.action == "upsert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            self.client.upserts.append((self.name, payload, self.on_conflict))
            rows.extend(payload)
            return SimpleNamespace(data=payload)
        if self.columns is None:
            return SimpleNamespace(data=matched)
        return SimpleNamespace(
            data=[
                {column: row.get(column) for column in self.columns}
                for row in matched
            ]
        )


class _FakeSupabase:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.upserts = []

    def table(self, name):
        return _FakeTable(self, name)


def test_build_backfill_records_creates_artifact_spans_and_chunks():
    row = {
        "id": 123,
        "document_hash": "existing-doc-hash",
        "parsed_data": {
            "full_text": (
                "# Rates\n\n"
                "Duration should rally if payrolls cool.\n\n"
                "Credit spreads may widen."
            )
        },
    }

    records = build_backfill_records(
        row,
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
    )

    artifact = records["artifact"]
    spans = records["spans"]
    chunks = records["chunks"]

    assert artifact["research_id"] == 123
    assert artifact["document_hash"] == "existing-doc-hash"
    assert artifact["parser_version"] == "parser-test"
    assert artifact["artifact_manifest"]["span_version"] == "span-test"
    assert len(spans) == 3
    assert {span["research_id"] for span in spans} == {123}
    assert spans[0]["span_type"] == "section"
    assert spans[1]["section_path"] == ["Rates"]
    assert len(chunks) == 1
    assert chunks[0]["research_id"] == 123
    assert chunks[0]["span_keys"] == [span["span_key"] for span in spans]
    assert chunks[0]["chunker_version"] == "chunk-test"
    assert chunks[0]["chunk_type"] == "semantic"


def test_build_backfill_records_hashes_full_text_when_document_hash_missing():
    row = {
        "id": "123",
        "parsed_data": {
            "full_text": "A paragraph.",
        },
    }

    records = build_backfill_records(row)

    artifact = records["artifact"]
    spans = records["spans"]

    assert artifact["document_hash"]
    assert spans[0]["document_hash"] == artifact["document_hash"]


def test_build_backfill_records_namespaces_keys_by_research_id():
    base_row = {
        "document_hash": "same-doc-hash",
        "parsed_data": {
            "full_text": "Same paragraph.",
        },
    }

    first = build_backfill_records({"id": 1, **base_row})
    second = build_backfill_records({"id": 2, **base_row})

    assert first["spans"][0]["document_hash"] == second["spans"][0]["document_hash"]
    assert first["spans"][0]["span_key"] != second["spans"][0]["span_key"]
    assert first["chunks"][0]["chunk_key"] != second["chunks"][0]["chunk_key"]


def test_build_backfill_records_rejects_empty_full_text():
    row = {"id": 123, "parsed_data": {"full_text": ""}}

    try:
        build_backfill_records(row)
    except ValueError as exc:
        assert "full_text is empty" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_validate_no_key_drift_allows_identical_existing_rows():
    row = {
        "id": 123,
        "document_hash": "doc-hash",
        "parsed_data": {"full_text": "First paragraph.\n\nSecond paragraph."},
    }
    records = build_backfill_records(
        row,
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
    )
    client = _FakeSupabase(
        {
            "research_spans": [
                {
                    "research_id": 123,
                    "span_version": "span-test",
                    "span_order": records["spans"][0]["span_order"],
                    "span_key": records["spans"][0]["span_key"],
                }
            ],
            "research_retrieval_chunks": [
                {
                    "research_id": 123,
                    "chunker_version": "chunk-test",
                    "chunk_order": records["chunks"][0]["chunk_order"],
                    "chunk_key": records["chunks"][0]["chunk_key"],
                }
            ],
        }
    )

    validate_no_key_drift(client, records)


def test_validate_no_key_drift_rejects_same_version_span_key_drift():
    row = {
        "id": 123,
        "document_hash": "doc-hash",
        "parsed_data": {"full_text": "First paragraph.\n\nSecond paragraph."},
    }
    records = build_backfill_records(
        row,
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
    )
    client = _FakeSupabase(
        {
            "research_spans": [
                {
                    "research_id": 123,
                    "span_version": "span-test",
                    "span_order": records["spans"][0]["span_order"],
                    "span_key": "old-span-key",
                }
            ],
            "research_retrieval_chunks": [],
        }
    )

    with pytest.raises(ValueError, match="same-version memory rows have different keys"):
        validate_no_key_drift(client, records)


def test_process_record_replace_requires_explicit_warning_and_deletes_existing_rows(capsys):
    row = {
        "id": 123,
        "document_hash": "doc-hash",
        "parsed_data": {"full_text": "First paragraph.\n\nSecond paragraph."},
    }
    client = _FakeSupabase(
        {
            "research_document_artifacts": [
                {"id": 1, "research_id": 123, "parser_version": "parser-test"}
            ],
            "research_spans": [
                {"id": 2, "research_id": 123, "span_version": "span-test"}
            ],
            "research_retrieval_chunks": [
                {"id": 3, "research_id": 123, "chunker_version": "chunk-test"}
            ],
        }
    )
    args = SimpleNamespace(
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
        overlap_spans=1,
        dry_run=False,
        replace=True,
    )

    process_record(client, row, args)

    output = capsys.readouterr().out
    assert "REPLACE WARNING" in output
    assert "artifacts=1 spans=1 chunks=1" in output
    assert {"id": 1, "research_id": 123, "parser_version": "parser-test"} not in client.rows[
        "research_document_artifacts"
    ]


def test_validate_args_requires_confirm_replace():
    args = SimpleNamespace(
        batch_size=50,
        limit=None,
        min_chars=1800,
        target_chars=6000,
        overlap_spans=1,
        replace=True,
        confirm_replace=False,
    )

    with pytest.raises(SystemExit, match="--replace requires --confirm-replace"):
        validate_args(args)
