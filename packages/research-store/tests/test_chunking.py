from distill_tool.chunking import split_fallback_chunks


def test_split_fallback_chunks_splits_single_long_paragraph_by_sentence() -> None:
    text = " ".join([f"This is sentence number {i}." for i in range(1, 181)])

    pages = split_fallback_chunks(text, target_chars=180, min_chars=60)

    assert len(pages) > 1
    assert max(len(page.text) for page in pages[:-1]) <= 180


def test_split_fallback_chunks_splits_single_long_paragraph_by_words_when_no_sentence_breaks() -> None:
    text = " ".join(["token"] * 1200)

    pages = split_fallback_chunks(text, target_chars=120, min_chars=20)

    assert len(pages) > 1
    assert max(len(page.text) for page in pages) <= 120
