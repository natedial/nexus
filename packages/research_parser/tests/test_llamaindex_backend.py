from types import SimpleNamespace

import pytest

from src.parser import BlockType, LlamaIndexBackend, TextBlock


class FakeLlamaIndexParser:
    def __init__(self, markdown: str | None, error: str | None = None):
        self._markdown = markdown
        self._error = error
        self.call_count = 0

    def parse(self, pdf_path):
        self.call_count += 1
        return SimpleNamespace(markdown=self._markdown, error=self._error)


def test_parse_text_returns_raw_output():
    parser = FakeLlamaIndexParser(markdown="hello")
    backend = LlamaIndexBackend(parser=parser)

    result = backend.parse_text("fake.pdf")

    assert result.raw_output == "hello"
    assert len(result.blocks) == 1
    assert result.blocks[0].block_type == BlockType.PARAGRAPH
    assert result.blocks[0].text == "hello"


def test_parse_text_normalizes_markdown():
    parser = FakeLlamaIndexParser(
        markdown="Line one\r\n## Heading\r\n- Item\r\n\r\n\r\nTail paragraph\r\n"
    )
    backend = LlamaIndexBackend(parser=parser)

    result = backend.parse_text("fake.pdf")

    assert "\r" not in result.raw_output
    assert "\n\n\n" not in result.raw_output
    assert "Line one\n\n## Heading" in result.raw_output
    assert "## Heading\n\n- Item" in result.raw_output
    assert result.blocks[0].block_type == BlockType.PARAGRAPH
    assert result.blocks[0].text == "Line one"
    assert result.blocks[1].block_type == BlockType.HEADING
    assert result.blocks[2].block_type == BlockType.LIST_ITEM
    assert result.blocks[3].block_type == BlockType.PARAGRAPH


def test_parse_text_raises_on_empty_markdown():
    parser = FakeLlamaIndexParser(markdown="", error="no markdown")
    backend = LlamaIndexBackend(parser=parser)

    with pytest.raises(ValueError) as excinfo:
        backend.parse_text("fake.pdf")

    assert "no markdown" in str(excinfo.value)


def test_parse_text_raises_on_whitespace_markdown():
    parser = FakeLlamaIndexParser(markdown=" \n\t")
    backend = LlamaIndexBackend(parser=parser)

    with pytest.raises(ValueError) as excinfo:
        backend.parse_text("fake.pdf")

    assert "Empty markdown" in str(excinfo.value)


def test_extract_figures_returns_empty_without_parsing():
    parser = FakeLlamaIndexParser(markdown="hello")
    backend = LlamaIndexBackend(parser=parser)

    figures = backend.extract_figures("fake.pdf")

    assert figures == []
    assert parser.call_count == 0


def test_confidence_returns_pass():
    parser = FakeLlamaIndexParser(markdown="hello")
    backend = LlamaIndexBackend(parser=parser)

    blocks = [
        TextBlock(block_type=BlockType.HEADING, text="Title", level=1),
        TextBlock(block_type=BlockType.PARAGRAPH, text="A" * 1200),
        TextBlock(block_type=BlockType.PARAGRAPH, text="B" * 1200),
        TextBlock(block_type=BlockType.PARAGRAPH, text="C" * 1200),
        TextBlock(block_type=BlockType.LIST_ITEM, text="Item"),
    ]
    confidence = backend.confidence(blocks, [])

    assert confidence.status == "PASS"
    assert confidence.score >= 0.75


def test_confidence_flags_low_paragraph_count():
    parser = FakeLlamaIndexParser(markdown="hello")
    backend = LlamaIndexBackend(parser=parser)

    blocks = [
        TextBlock(block_type=BlockType.HEADING, text="Title", level=1),
        TextBlock(block_type=BlockType.PARAGRAPH, text="A" * 1500),
        TextBlock(block_type=BlockType.PARAGRAPH, text="B" * 1500),
        TextBlock(block_type=BlockType.LIST_ITEM, text="Item"),
    ]
    confidence = backend.confidence(blocks, [])

    assert "low_paragraph_count" in confidence.reasons
    assert confidence.status in {"REPAIR", "FALLBACK"}


def test_confidence_flags_very_long_paragraph():
    parser = FakeLlamaIndexParser(markdown="hello")
    backend = LlamaIndexBackend(parser=parser)

    blocks = [
        TextBlock(block_type=BlockType.HEADING, text="Title", level=1),
        TextBlock(block_type=BlockType.PARAGRAPH, text="A" * 4000),
        TextBlock(block_type=BlockType.PARAGRAPH, text="B" * 200),
        TextBlock(block_type=BlockType.LIST_ITEM, text="Item"),
    ]
    confidence = backend.confidence(blocks, [])

    assert "very_long_paragraph" in confidence.reasons
    assert confidence.status in {"REPAIR", "FALLBACK"}
