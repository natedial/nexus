"""LlamaIndex-backed parser implementation."""

from __future__ import annotations

from pathlib import Path

from .artifacts import markdown_to_blocks, normalize_markdown
from .backend import BlockType, FigureRecord, ParserBackend, TextBlock, TextParseResult
from .llamaindex import LlamaIndexParser


class LlamaIndexBackend(ParserBackend):
    def __init__(self, parser: LlamaIndexParser):
        self._parser = parser

    def parse_text(self, pdf_path: Path) -> TextParseResult:
        parse_result = self._parser.parse(pdf_path)
        markdown = normalize_markdown(parse_result.markdown or "")
        if not markdown or not markdown.strip():
            message = parse_result.error or "Empty markdown returned"
            raise ValueError(message)

        blocks = markdown_to_blocks(markdown)
        if not blocks:
            blocks = [TextBlock(block_type=BlockType.PARAGRAPH, text=markdown.strip())]

        return TextParseResult(blocks=blocks, raw_output=markdown)

    def extract_figures(self, pdf_path: Path) -> list[FigureRecord]:
        return []

    # Inherit default confidence heuristics from ParserBackend.
