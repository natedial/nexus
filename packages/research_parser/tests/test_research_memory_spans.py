from src.parser import BlockType, TextBlock
from src.research_memory import (
    build_paragraph_spans,
    build_retrieval_chunks,
    build_spans_from_blocks,
)


def test_build_paragraph_spans_preserves_pages_and_sections():
    text = "\n".join(
        [
            "--- PAGE 1 ---",
            "# Rates Outlook",
            "",
            "The market expects cuts to begin later in the year.",
            "",
            "--- PAGE 2 ---",
            "Higher term premium would push long-end yields higher.",
        ]
    )

    spans = build_paragraph_spans(text, document_hash="doc-hash")

    assert [span.span_type for span in spans] == ["section", "paragraph", "paragraph"]
    assert spans[0].section_path == ("Rates Outlook",)
    assert spans[1].section_path == ("Rates Outlook",)
    assert spans[1].page_start == 1
    assert spans[2].page_start == 2
    assert spans[1].paragraph_start == 1
    assert spans[2].paragraph_start == 2


def test_build_paragraph_spans_is_stable_for_same_input():
    text = "# Header\n\nFirst paragraph.\n\nSecond paragraph."

    first = build_paragraph_spans(text, document_hash="doc-hash")
    second = build_paragraph_spans(text, document_hash="doc-hash")

    assert [span.span_key for span in first] == [span.span_key for span in second]
    assert [span.text_hash for span in first] == [span.text_hash for span in second]


def test_build_paragraph_spans_defaults_to_page_one_without_markers():
    spans = build_paragraph_spans("First paragraph.\n\nSecond paragraph.", document_hash="doc-hash")

    assert len(spans) == 2
    assert {span.page_start for span in spans} == {1}
    assert {span.page_end for span in spans} == {1}


def test_build_retrieval_chunks_tracks_span_keys_and_page_range():
    text = "\n\n".join(
        [
            "--- PAGE 1 ---",
            "# Macro",
            "A" * 900,
            "B" * 900,
            "--- PAGE 2 ---",
            "C" * 900,
        ]
    )
    spans = build_paragraph_spans(text, document_hash="doc-hash")

    chunks = build_retrieval_chunks(
        spans,
        document_hash="doc-hash",
        target_chars=1200,
        min_chars=800,
        overlap_spans=1,
    )

    assert len(chunks) >= 2
    assert chunks[0].span_keys
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    assert chunks[0].chunk_key != chunks[-1].chunk_key


def test_build_spans_from_blocks_preserves_tables_pages_and_coordinates():
    blocks = [
        TextBlock(block_type=BlockType.HEADING, text="Rates Outlook", page=1, level=1),
        TextBlock(
            block_type=BlockType.PARAGRAPH,
            text="Duration should rally if payrolls cool.",
            page=1,
            bbox=[0.0, 1.0, 2.0, 3.0],
        ),
        TextBlock(
            block_type=BlockType.TABLE,
            text="| Tenor | Yield |\n| 2y | 3.8 |",
            page=2,
        ),
    ]

    spans = build_spans_from_blocks(blocks, document_hash="doc-hash")

    assert [span.span_type for span in spans] == ["section", "paragraph", "table"]
    assert spans[1].section_path == ("Rates Outlook",)
    assert spans[1].page_start == 1
    assert spans[1].coordinates == {"bbox": [0.0, 1.0, 2.0, 3.0]}
    assert spans[2].page_start == 2
    assert spans[2].span_type == "table"


def test_build_spans_from_blocks_is_stable_for_same_input():
    blocks = [
        TextBlock(block_type=BlockType.PARAGRAPH, text="First paragraph.", page=1),
        TextBlock(block_type=BlockType.PARAGRAPH, text="Second paragraph.", page=2),
    ]

    first = build_spans_from_blocks(blocks, document_hash="doc-hash")
    second = build_spans_from_blocks(blocks, document_hash="doc-hash")

    assert [span.span_key for span in first] == [span.span_key for span in second]
