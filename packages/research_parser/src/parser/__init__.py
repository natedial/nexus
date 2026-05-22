"""PDF parsing utilities and backends."""

from .artifacts import (
    blocks_to_markdown,
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
from .docling_backend import DoclingBackend
from .llamaindex import LlamaIndexParser
from .llamaindex_backend import LlamaIndexBackend
from .mineru_backend import MinerUBackend

__all__ = [
    "BlockType",
    "ConfidenceResult",
    "DoclingBackend",
    "FigureRecord",
    "LlamaIndexBackend",
    "LlamaIndexParser",
    "MinerUBackend",
    "ParserBackend",
    "TextBlock",
    "TextParseResult",
    "blocks_to_markdown",
    "markdown_to_blocks",
    "normalize_markdown",
    "paragraph_stats",
    "write_artifacts",
]
