import pytest

from src.research_memory.backfill import build_backfill_records


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

    assert records["artifact"]["research_id"] == 123
    assert records["artifact"]["parser_version"] == "parser-test"
    assert records["spans"]
    assert records["chunks"]
    assert records["spans"][0]["span_version"] == "span-test"
    assert records["chunks"][0]["chunker_version"] == "chunk-test"


def test_build_backfill_records_hashes_full_text_when_document_hash_missing():
    row = {
        "id": 123,
        "parsed_data": {"full_text": "Only body text"},
    }

    records = build_backfill_records(
        row,
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
    )

    assert records["artifact"]["document_hash"]
    assert records["artifact"]["document_hash"] != "existing-doc-hash"


def test_build_backfill_records_namespaces_keys_by_research_id():
    row = {
        "id": 456,
        "document_hash": "doc-hash",
        "parsed_data": {"full_text": "Paragraph one.\n\nParagraph two."},
    }

    records = build_backfill_records(
        row,
        parser_version="parser-test",
        span_version="span-test",
        chunker_version="chunk-test",
        target_chars=2000,
        min_chars=200,
    )

    assert all(span["research_id"] == 456 for span in records["spans"])
    assert all(chunk["research_id"] == 456 for chunk in records["chunks"])


def test_build_backfill_records_rejects_empty_full_text():
    row = {"id": 123, "parsed_data": {"full_text": ""}}

    with pytest.raises(ValueError, match="full_text is empty"):
        build_backfill_records(
            row,
            parser_version="parser-test",
            span_version="span-test",
            chunker_version="chunk-test",
            target_chars=2000,
            min_chars=200,
        )
