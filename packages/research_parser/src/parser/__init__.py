"""PDF parsing utilities and backends."""

from .artifacts import (
    block_from_dict,
    block_to_dict,
    blocks_to_markdown,
    filter_blocks_present_in_text,
    load_blocks,
    markdown_to_blocks,
    normalize_markdown,
    paragraph_stats,
    write_artifacts,
)
from .backend import (
    BlockType,
    ConfidenceResult,
    FigureRecord,
    ParserBackend,
    TextBlock,
    TextParseResult,
)
from .boilerplate import strip_boilerplate
from .docling_backend import DoclingBackend, blocks_from_docling_document
from .mineru_backend import MinerUBackend
from .routing import ParsedDocument, parse_with_fallback, parse_with_optional_ocr

__all__ = [
    "BlockType",
    "ConfidenceResult",
    "DoclingBackend",
    "FigureRecord",
    "MinerUBackend",
    "ParsedDocument",
    "ParserBackend",
    "TextBlock",
    "TextParseResult",
    "block_from_dict",
    "block_to_dict",
    "blocks_from_docling_document",
    "blocks_to_markdown",
    "filter_blocks_present_in_text",
    "load_blocks",
    "markdown_to_blocks",
    "normalize_markdown",
    "paragraph_stats",
    "parse_with_fallback",
    "parse_with_optional_ocr",
    "strip_boilerplate",
    "write_artifacts",
]
