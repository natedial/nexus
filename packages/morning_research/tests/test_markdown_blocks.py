"""Markdown block conversion tests."""

from __future__ import annotations

from morning_research.markdown_blocks import extract_title, markdown_to_blocks


def test_heading_and_paragraph() -> None:
    blocks = markdown_to_blocks("# Title\n\nHello world\n\n- item\n")
    assert blocks[0]["type"] == "heading_1"
    assert blocks[1]["type"] == "paragraph"
    assert blocks[2]["type"] == "bulleted_list_item"
    assert extract_title("# Title\n\nBody", fallback="x") == "Title"
