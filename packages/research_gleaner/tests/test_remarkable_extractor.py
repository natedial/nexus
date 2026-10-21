import io
import json
import zipfile
from datetime import UTC, datetime

from research_gleaner.models import CaptureIntent
from research_gleaner.remarkable.client import RemarkableDocument
from research_gleaner.remarkable.extractor import (
    REMARKABLE_HIGHLIGHT_RGBA,
    HighlightFragment,
    _page_order,
    _source_style,
    extract_document,
    merge_fragments,
)


def fragment(text, *, color_id=5, color_name="pink", color_rgba=None, y=10):
    return HighlightFragment(
        page_number=2,
        page_id="page-2",
        text=text,
        color_id=color_id,
        color_name=color_name,
        color_rgba=color_rgba,
        rectangles=((10.0, float(y), 40.0, 8.0),),
    )


def test_merge_fragments_joins_adjacent_same_color_only():
    groups = merge_fragments(
        [
            fragment("First", y=10),
            fragment("second", y=19),
            fragment("Different", color_id=3, color_name="yellow", y=28),
        ]
    )

    assert [[item.text for item in group] for group in groups] == [
        ["First", "second"],
        ["Different"],
    ]


def test_extract_document_preserves_native_color_and_geometry(monkeypatch):
    document = RemarkableDocument(
        document_id="doc-1",
        revision="rev-2",
        title="OAT Dealers Moving Inventory",
        path="/SG Platform/Processing/OAT Dealers Moving Inventory",
        modified_at=datetime(2026, 10, 13, 17, tzinfo=UTC),
        raw=object(),
    )
    monkeypatch.setattr(
        "research_gleaner.remarkable.extractor.extract_fragments",
        lambda archive: [fragment("Dealer inventory")],
    )

    capture = extract_document(
        document,
        b"archive",
        routes={"pink": CaptureIntent.RESEARCH},
    )[0]

    assert capture.source_style == "pink"
    assert capture.intent == CaptureIntent.RESEARCH
    assert capture.locator.page_number == 2
    assert capture.locator.coordinates == (10.0, 10.0, 50.0, 18.0)
    assert capture.metadata["remarkable_color_id"] == 5
    assert capture.metadata["remarkable_color_enum"] == "pink"
    assert capture.metadata["remarkable_color_rgba"] is None
    assert capture.metadata["remarkable_fragments"][0]["rectangles"] == [[10.0, 10.0, 40.0, 8.0]]
    assert "category" not in capture.to_dict()


def test_page_order_supports_legacy_pdf_manifest():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("document.content", json.dumps({"pages": ["page-a", "page-b"]}))

    with zipfile.ZipFile(io.BytesIO(archive.getvalue())) as source:
        assert _page_order(source) == ["page-a", "page-b"]


def test_rgba_override_resolves_current_remarkable_highlight_palette(monkeypatch):
    document = RemarkableDocument(
        document_id="doc-orange",
        revision="rev-1",
        title="Color test",
        path="/Color test",
        modified_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        raw=object(),
    )
    monkeypatch.setattr(
        "research_gleaner.remarkable.extractor.extract_fragments",
        lambda archive: [
            fragment(
                "Orange evidence",
                color_id=9,
                color_name="highlight",
                color_rgba=(255, 195, 140, 255),
            )
        ],
    )

    capture = extract_document(document, b"archive")[0]

    assert capture.source_style == "orange"
    assert capture.metadata["remarkable_color_id"] == 9
    assert capture.metadata["remarkable_color_enum"] == "highlight"
    assert capture.metadata["remarkable_color_rgba"] == [255, 195, 140, 255]


def test_current_remarkable_highlight_palette_has_distinct_source_styles():
    resolved = {
        _source_style(
            fragment(
                name,
                color_id=9,
                color_name="highlight",
                color_rgba=rgba,
            )
        )
        for rgba, name in REMARKABLE_HIGHLIGHT_RGBA.items()
    }

    assert resolved == {"yellow", "blue", "pink", "orange", "green"}
