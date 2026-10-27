from datetime import UTC, datetime

import pytest

from research_gleaner.models import (
    CapturedExcerpt,
    CaptureIntent,
    SourceDocumentRef,
    SourceLocator,
)


def document() -> SourceDocumentRef:
    return SourceDocumentRef(
        source_kind="notion",
        document_id="page-1",
        uri="https://notion.so/page-1",
        title="Rates",
        modified_at=datetime(2026, 10, 12, tzinfo=UTC),
    )


def test_capture_id_is_stable_across_capture_times():
    locator = SourceLocator(block_id="block-1", char_start=2, char_end=10)
    first = CapturedExcerpt.create(
        document=document(),
        locator=locator,
        text="  Higher   yields ",
        context_text="Higher yields may slow housing.",
        source_style="green",
        captured_at=datetime(2026, 10, 12, tzinfo=UTC),
    )
    second = CapturedExcerpt.create(
        document=document(),
        locator=locator,
        text="Higher yields",
        context_text="Changed surrounding context",
        source_style="green",
        captured_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    assert first.capture_id == second.capture_id
    assert first.text == "Higher yields"


def test_locator_metadata_participates_in_identity():
    first = CapturedExcerpt.create(
        document=document(),
        locator=SourceLocator(
            block_id="row-1",
            char_start=0,
            char_end=4,
            metadata={"cell_index": 0},
        ),
        text="Same",
        context_text="Same",
        source_style="blue",
    )
    second = CapturedExcerpt.create(
        document=document(),
        locator=SourceLocator(
            block_id="row-1",
            char_start=0,
            char_end=4,
            metadata={"cell_index": 1},
        ),
        text="Same",
        context_text="Same",
        source_style="blue",
    )

    assert first.capture_id != second.capture_id


def test_source_style_participates_in_identity():
    locator = SourceLocator(block_id="block-1", char_start=0, char_end=4)
    pink = CapturedExcerpt.create(
        document=document(),
        locator=locator,
        text="Same",
        context_text="Same",
        source_style="pink",
    )
    blue = CapturedExcerpt.create(
        document=document(),
        locator=locator,
        text="Same",
        context_text="Same",
        source_style="blue",
    )

    assert pink.capture_id != blue.capture_id


def test_capture_serializes_contract_fields():
    capture = CapturedExcerpt.create(
        document=document(),
        locator=SourceLocator(block_id="block-1", char_start=0, char_end=4),
        text="Idea",
        context_text="Idea with context",
        heading_path=("Macro", "Rates"),
        source_style="blue",
        intent=CaptureIntent.RESEARCH,
    )

    payload = capture.to_dict()

    assert payload["schema_version"] == 2
    assert "category" not in payload
    assert payload["intent"] == "research"
    assert payload["document"]["source_kind"] == "notion"
    assert payload["heading_path"] == ["Macro", "Rates"]


def test_empty_capture_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        CapturedExcerpt.create(
            document=document(),
            locator=SourceLocator(block_id="block-1"),
            text="  ",
            context_text="",
            source_style="blue",
        )
