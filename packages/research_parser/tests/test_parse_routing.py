from pathlib import Path

import pytest

from src.parser import (
    BlockType,
    ConfidenceResult,
    TextBlock,
    TextParseResult,
    parse_with_fallback,
)
from src.parser.routing import ParsedDocument


class _FakeBackend:
    def __init__(
        self,
        *,
        markdown: str = "hello",
        status: str = "PASS",
        score: float = 0.9,
        error: Exception | None = None,
    ):
        self.markdown = markdown
        self.status = status
        self.score = score
        self.error = error
        self.parse_calls = 0

    def parse_text(self, pdf_path: Path) -> TextParseResult:
        self.parse_calls += 1
        if self.error is not None:
            raise self.error
        return TextParseResult(
            blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text=self.markdown, page=1)],
            raw_output=self.markdown,
        )

    def extract_figures(self, pdf_path: Path):
        return []

    def confidence(self, blocks, figures) -> ConfidenceResult:
        return ConfidenceResult(score=self.score, status=self.status, reasons=[])


def test_parse_with_fallback_stops_on_repair():
    fallback = _FakeBackend(status="FALLBACK", score=0.2)
    repair = _FakeBackend(status="REPAIR", score=0.6, markdown="repaired")
    unused = _FakeBackend(status="PASS", score=0.9)

    parsed = parse_with_fallback(
        [("docling", fallback), ("mineru", repair), ("unused", unused)],
        Path("note.pdf"),
    )

    assert parsed.backend_name == "mineru"
    assert parsed.text_result.raw_output == "repaired"
    assert unused.parse_calls == 0


def test_parse_with_fallback_skips_exceptions_and_uses_pass():
    broken = _FakeBackend(error=RuntimeError("docling down"))
    ok = _FakeBackend(status="PASS", score=0.85, markdown="ok")

    parsed = parse_with_fallback(
        [("docling", broken), ("mineru", ok)],
        Path("note.pdf"),
    )

    assert parsed.backend_name == "mineru"
    assert parsed.confidence.status == "PASS"


def test_parse_with_fallback_keeps_highest_fallback_score():
    weak = _FakeBackend(status="FALLBACK", score=0.1, markdown="weak")
    better = _FakeBackend(status="FALLBACK", score=0.35, markdown="better")

    parsed = parse_with_fallback(
        [("docling", weak), ("mineru", better)],
        Path("note.pdf"),
    )

    assert parsed.backend_name == "mineru"
    assert parsed.text_result.raw_output == "better"


def test_parse_with_fallback_raises_when_all_backends_fail():
    with pytest.raises(RuntimeError, match="Parse failed"):
        parse_with_fallback(
            [
                ("docling", _FakeBackend(error=RuntimeError("a"))),
                ("mineru", _FakeBackend(error=RuntimeError("b"))),
            ],
            Path("note.pdf"),
        )


def test_parsed_document_is_dataclass_shape():
    parsed = ParsedDocument(
        backend_name="docling",
        text_result=TextParseResult(blocks=[], raw_output="x"),
        figures=[],
        confidence=ConfidenceResult(score=1.0, status="PASS", reasons=[]),
    )
    assert parsed.backend_name == "docling"
