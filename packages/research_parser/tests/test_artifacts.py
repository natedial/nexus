import json
import os

import pytest

from src.parser import (
    BlockType,
    FigureRecord,
    TextBlock,
    TextParseResult,
    markdown_to_blocks,
    normalize_markdown,
    paragraph_stats,
    write_artifacts,
)


def test_write_document_md_from_raw_output(tmp_path):
    text_result = TextParseResult(blocks=[], raw_output="raw text")
    artifact_dir = tmp_path / "artifacts"

    write_artifacts(artifact_dir, text_result, [])

    content = (artifact_dir / "document.md").read_text(encoding="utf-8")
    assert content == "raw text\n"


def test_write_document_md_from_blocks(tmp_path):
    blocks = [
        TextBlock(block_type=BlockType.HEADING, text="Heading", level=2),
        TextBlock(block_type=BlockType.PARAGRAPH, text="Paragraph"),
        TextBlock(block_type=BlockType.LIST_ITEM, text="Item"),
        TextBlock(block_type=BlockType.PARAGRAPH, text="   "),
    ]
    text_result = TextParseResult(blocks=blocks, raw_output=None)
    artifact_dir = tmp_path / "artifacts"

    write_artifacts(artifact_dir, text_result, [])

    content = (artifact_dir / "document.md").read_text(encoding="utf-8")
    assert content == "## Heading\n\nParagraph\n\n- Item\n"


def test_figures_jsonl_empty_when_no_figures(tmp_path):
    text_result = TextParseResult(blocks=[], raw_output="raw")
    artifact_dir = tmp_path / "artifacts"

    write_artifacts(artifact_dir, text_result, [])

    figures_path = artifact_dir / "figures.jsonl"
    assert figures_path.exists()
    assert figures_path.read_text(encoding="utf-8") == ""


def test_figures_jsonl_serializes_correctly(tmp_path):
    text_result = TextParseResult(blocks=[], raw_output="raw")
    artifact_dir = tmp_path / "artifacts"
    figures = [
        FigureRecord(
            figure_id="fig-1",
            page=3,
            bbox=[0.1, 0.2, 0.3, 0.4],
            caption_text="Caption",
            section_path=["Section A", "Section B"],
            image_path="figures/fig-1.png",
            content_hash="hash123",
        )
    ]

    write_artifacts(artifact_dir, text_result, figures)

    lines = (artifact_dir / "figures.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["figure_id"] == "fig-1"
    assert payload["page"] == 3
    assert payload["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert payload["caption_text"] == "Caption"
    assert payload["section_path"] == ["Section A", "Section B"]
    assert payload["image_path"] == "figures/fig-1.png"
    assert payload["content_hash"] == "hash123"


def test_artifact_dir_created_if_missing(tmp_path):
    text_result = TextParseResult(blocks=[], raw_output="raw")
    artifact_dir = tmp_path / "missing" / "nested"

    write_artifacts(artifact_dir, text_result, [])

    assert artifact_dir.exists()


def test_exceptions_propagate(tmp_path):
    text_result = TextParseResult(blocks=[], raw_output="raw")
    artifact_dir = tmp_path / "locked"
    artifact_dir.mkdir()
    os.chmod(artifact_dir, 0)

    try:
        with pytest.raises(Exception):
            write_artifacts(artifact_dir, text_result, [])
    finally:
        os.chmod(artifact_dir, 0o700)


def test_markdown_to_blocks_parses_minimal_structures():
    markdown = (
        "# Title\n\nParagraph line one.\nParagraph line two.\n\n- Item one\n"
        "1. Item two\n• Item three\n"
    )

    blocks = markdown_to_blocks(markdown)

    assert blocks[0].block_type == BlockType.HEADING
    assert blocks[0].text == "Title"
    assert blocks[1].block_type == BlockType.PARAGRAPH
    assert blocks[1].text == "Paragraph line one. Paragraph line two."
    assert blocks[2].block_type == BlockType.LIST_ITEM
    assert blocks[2].text == "Item one"
    assert blocks[3].block_type == BlockType.LIST_ITEM
    assert blocks[3].text == "Item two"
    assert blocks[4].block_type == BlockType.LIST_ITEM
    assert blocks[4].text == "Item three"


def test_normalize_markdown_enforces_blank_lines_and_newlines():
    markdown = (
        "Line one\r\n## Heading\r\n- Item one\r\n- Item two\r\n\r\n\r\n"
        "Tail paragraph\r\n1. Numbered item\r\n"
    )

    normalized = normalize_markdown(markdown)

    assert "\r" not in normalized
    assert "\n\n\n" not in normalized
    assert "Line one\n\n## Heading" in normalized
    assert "## Heading\n\n- Item one" in normalized
    assert "- Item two\n\nTail paragraph" in normalized
    assert "Tail paragraph\n\n1. Numbered item" in normalized


def test_paragraph_stats_reports_expected_values():
    markdown = "One\n\nTwo\n\nThree"

    paragraph_count, max_paragraph_chars, total_chars = paragraph_stats(markdown)

    assert paragraph_count == 3
    assert max_paragraph_chars == len("Three")
    assert total_chars == len(markdown)


def test_paragraph_stats_handles_empty_text():
    paragraph_count, max_paragraph_chars, total_chars = paragraph_stats(" \n\t")

    assert paragraph_count == 0
    assert max_paragraph_chars == 0
    assert total_chars == 0
