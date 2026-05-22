"""Parser backend abstractions and data models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FIGURE_REF = "figure_ref"
    TABLE = "table"


@dataclass
class TextBlock:
    block_type: BlockType
    text: str
    page: int | None = None
    level: int | None = None
    bbox: list[float] | None = None


@dataclass
class FigureRecord:
    figure_id: str
    page: int
    section_path: list[str]
    bbox: list[float] | None = None
    caption_text: str | None = None
    image_path: str | None = None
    content_hash: str | None = None


@dataclass
class ConfidenceResult:
    score: float
    status: Literal["PASS", "REPAIR", "FALLBACK"]
    reasons: list[str]


@dataclass
class TextParseResult:
    blocks: list[TextBlock]
    raw_output: str | None


class ParserBackend(ABC):
    @abstractmethod
    def parse_text(self, pdf_path: Path) -> TextParseResult:
        raise NotImplementedError

    @abstractmethod
    def extract_figures(self, pdf_path: Path) -> list[FigureRecord]:
        raise NotImplementedError

    def confidence(
        self, blocks: list[TextBlock], figures: list[FigureRecord]
    ) -> ConfidenceResult:
        score = 0.5
        reasons: list[str] = []

        total_text = sum(len(block.text.strip()) for block in blocks if block.text)
        headings = sum(1 for block in blocks if block.block_type == BlockType.HEADING)
        list_items = sum(1 for block in blocks if block.block_type == BlockType.LIST_ITEM)
        paragraphs = sum(1 for block in blocks if block.block_type == BlockType.PARAGRAPH)
        paragraph_lengths = [
            len(block.text.strip())
            for block in blocks
            if block.block_type == BlockType.PARAGRAPH and block.text and block.text.strip()
        ]
        max_paragraph_chars = max(paragraph_lengths, default=0)

        if total_text < 200:
            score -= 0.3
            reasons.append("very_low_text")
        elif total_text < 1000:
            score -= 0.1
            reasons.append("low_text")
        elif total_text > 3000:
            score += 0.1

        if headings == 0:
            score -= 0.1
            reasons.append("no_headings")
        else:
            score += 0.1

        if list_items == 0:
            score -= 0.05
            reasons.append("no_lists")
        else:
            score += 0.05

        if paragraphs == 0:
            score -= 0.1
            reasons.append("no_paragraphs")
        else:
            score += 0.05

        if total_text >= 3000 and paragraphs < 3:
            score -= 0.2
            reasons.append("low_paragraph_count")

        if max_paragraph_chars > 2500:
            score -= 0.2
            reasons.append("very_long_paragraph")

        score = max(0.0, min(1.0, score))
        if score >= 0.75:
            status = "PASS"
        elif score >= 0.4:
            status = "REPAIR"
        else:
            status = "FALLBACK"

        return ConfidenceResult(score=score, status=status, reasons=reasons)
