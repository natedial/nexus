from src.extraction.input_slicing import (
    chunk_for_structured_extraction,
    trim_for_structured_extraction,
)


def test_trim_for_structured_extraction_keeps_head_middle_and_tail_markers():
    head = "HEAD-" * 4_000
    middle_a = "MIDDLE-A-" * 4_000
    middle_b = "MIDDLE-B-" * 4_000
    tail = "TAIL-" * 4_000
    text = head + middle_a + middle_b + tail

    trimmed = trim_for_structured_extraction(text)

    assert len(trimmed) < len(text)
    assert len(trimmed) <= 90_000
    assert trimmed.startswith(head[:18_000])
    assert tail[-12_000:] in trimmed
    assert "MIDDLE-A-" in trimmed
    assert "MIDDLE-B-" in trimmed
    assert "[...]" in trimmed


def test_trim_for_structured_extraction_leaves_short_documents_unchanged():
    text = "short document\n" * 200

    assert trim_for_structured_extraction(text) == text


def test_chunk_for_structured_extraction_covers_long_documents_with_overlap():
    paragraphs = [f"paragraph {idx}\nbody\n" for idx in range(18_000)]
    text = "\n".join(paragraphs)

    chunks = chunk_for_structured_extraction(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= 24_000 for chunk in chunks)
    assert "paragraph 0" in chunks[0]
    assert any("paragraph 9000" in chunk for chunk in chunks)
    assert "paragraph 17999" in chunks[-1]


def test_chunk_for_structured_extraction_accepts_custom_chunk_budget():
    paragraphs = [f"paragraph {idx}\nbody\n" for idx in range(2_000)]
    text = "\n".join(paragraphs)

    chunks = chunk_for_structured_extraction(
        text,
        max_chunk_chars=6_000,
        target_chunk_chars=4_500,
        min_progress_chars=2_000,
        overlap_chars=500,
    )

    assert len(chunks) > 1
    assert all(len(chunk) <= 6_000 for chunk in chunks)
