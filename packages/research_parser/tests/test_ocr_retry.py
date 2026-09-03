from pathlib import Path

from src.parser import (
    BlockType,
    ConfidenceResult,
    TextBlock,
    TextParseResult,
    parse_with_optional_ocr,
)
from src.parser.quality import ocr_retry_reasons, prefer_parse
from src.parser.routing import ParsedDocument
from tests.test_parse_routing import _FakeBackend


def _parsed(
    *,
    status: str,
    score: float,
    blocks: list[TextBlock],
    source_page_count: int | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        backend_name="docling",
        text_result=TextParseResult(
            blocks=blocks,
            raw_output="",
            source_page_count=source_page_count,
        ),
        figures=[],
        confidence=ConfidenceResult(score=score, status=status, reasons=[]),
    )


def test_ocr_retry_skips_healthy_chart_heavy_pass():
    blocks = [
        TextBlock(
            block_type=BlockType.PARAGRAPH,
            text="thesis paragraph with enough digital text. " * 20,
            page=page,
        )
        for page in range(1, 6)
    ]
    blocks.extend(
        [
            TextBlock(block_type=BlockType.FIGURE_REF, text="Exhibit 1: Rates", page=1),
            TextBlock(block_type=BlockType.FIGURE_REF, text="Exhibit 2: Labor", page=2),
            TextBlock(block_type=BlockType.FIGURE_REF, text="Figure 3: CPI surprise", page=3),
        ]
    )
    parsed = _parsed(status="PASS", score=0.9, blocks=blocks, source_page_count=5)
    assert ocr_retry_reasons(parsed) == []


def test_ocr_retry_pass_skips_stub_figures_when_pages_are_complete():
    """Chart-heavy PASS with generic figure labels still stays digital."""
    blocks = [
        TextBlock(
            block_type=BlockType.PARAGRAPH,
            text="body text with plenty of extracted characters. " * 10,
            page=page,
        )
        for page in range(1, 4)
    ]
    blocks.extend(
        [
            TextBlock(block_type=BlockType.FIGURE_REF, text="Figure", page=1),
            TextBlock(block_type=BlockType.FIGURE_REF, text="Figure 2", page=2),
        ]
    )
    parsed = _parsed(status="PASS", score=0.85, blocks=blocks, source_page_count=3)
    assert ocr_retry_reasons(parsed) == []


def test_ocr_retry_on_missing_pages_and_stub_figures():
    blocks = [
        TextBlock(block_type=BlockType.PARAGRAPH, text="body", page=1),
        TextBlock(block_type=BlockType.FIGURE_REF, text="Figure", page=1),
        TextBlock(block_type=BlockType.FIGURE_REF, text="Figure", page=2),
        TextBlock(block_type=BlockType.PARAGRAPH, text="tail", page=10),
    ]
    parsed = _parsed(status="REPAIR", score=0.7, blocks=blocks)
    reasons = ocr_retry_reasons(parsed)
    assert "missing_pages" in reasons
    assert "stub_figures" in reasons


def test_ocr_retry_when_pdf_has_trailing_empty_pages():
    """GS-style: body on 1-7, PDF has 10 pages, no holes in the span we saw."""
    blocks = [
        TextBlock(
            block_type=BlockType.PARAGRAPH,
            text="Hatzius letter paragraph with digital text. " * 8,
            page=page,
        )
        for page in range(1, 8)
    ]
    parsed = _parsed(status="REPAIR", score=0.7, blocks=blocks, source_page_count=10)
    assert "missing_pages" in ocr_retry_reasons(parsed)


def test_ocr_retry_pass_when_trailing_pages_are_missing():
    blocks = [
        TextBlock(
            block_type=BlockType.PARAGRAPH,
            text="digital body " * 40,
            page=page,
        )
        for page in range(1, 8)
    ]
    parsed = _parsed(status="PASS", score=0.9, blocks=blocks, source_page_count=10)
    assert ocr_retry_reasons(parsed) == ["missing_pages"]


def test_prefer_parse_keeps_digital_when_ocr_does_not_gain():
    digital = _parsed(
        status="REPAIR",
        score=0.7,
        blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="abcde" * 20, page=1)],
    )
    ocr = _parsed(
        status="REPAIR",
        score=0.71,
        blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="abcde" * 21, page=1)],
    )
    assert prefer_parse(digital, ocr) is digital


def test_prefer_parse_takes_ocr_text_gain():
    digital = _parsed(
        status="REPAIR",
        score=0.7,
        blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="short", page=1)],
    )
    ocr = _parsed(
        status="REPAIR",
        score=0.7,
        blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="short" * 20, page=1)],
    )
    assert prefer_parse(digital, ocr) is ocr


def test_parse_with_optional_ocr_does_not_construct_ocr_on_pass(tmp_path):
    digital = _FakeBackend(status="PASS", score=0.9, markdown="healthy note")
    constructed = {"n": 0}

    def factory():
        constructed["n"] += 1
        return _FakeBackend(status="PASS", score=0.95, markdown="ocr")

    parsed = parse_with_optional_ocr(
        digital_backend=digital,
        ocr_backend_factory=factory,
        mineru_backend=None,
        pdf_path=Path("note.pdf"),
        ocr_retry=True,
    )

    assert parsed.backend_name == "docling"
    assert constructed["n"] == 0
    assert parsed.ocr_retried is False


def test_parse_with_optional_ocr_retries_when_pages_are_missing(tmp_path):
    class _GappyBackend(_FakeBackend):
        def parse_text(self, pdf_path: Path) -> TextParseResult:
            self.parse_calls += 1
            return TextParseResult(
                blocks=[
                    TextBlock(block_type=BlockType.PARAGRAPH, text="open", page=1),
                    TextBlock(block_type=BlockType.FIGURE_REF, text="Figure", page=1),
                    TextBlock(block_type=BlockType.PARAGRAPH, text="close", page=8),
                ],
                raw_output="gappy",
                source_page_count=8,
            )

    digital = _GappyBackend(status="REPAIR", score=0.65)
    ocr = _FakeBackend(status="PASS", score=0.9, markdown="ocr recovered " * 40)
    parsed = parse_with_optional_ocr(
        digital_backend=digital,
        ocr_backend=ocr,
        mineru_backend=None,
        pdf_path=Path("note.pdf"),
    )

    assert parsed.ocr_retried is True
    assert "missing_pages" in parsed.ocr_retry_reasons
    assert parsed.backend_name == "docling-ocr"
    assert ocr.parse_calls == 1


def test_parse_with_optional_ocr_still_tries_mineru_after_weak_ocr(tmp_path):
    class _FallbackBackend(_FakeBackend):
        def parse_text(self, pdf_path: Path) -> TextParseResult:
            self.parse_calls += 1
            return TextParseResult(
                blocks=[
                    TextBlock(block_type=BlockType.PARAGRAPH, text="thin", page=1),
                    TextBlock(block_type=BlockType.PARAGRAPH, text="tail", page=4),
                ],
                raw_output="thin",
                source_page_count=4,
            )

    digital = _FallbackBackend(status="FALLBACK", score=0.2, markdown="thin")
    ocr = _FakeBackend(status="FALLBACK", score=0.21, markdown="thinish")
    mineru = _FakeBackend(status="PASS", score=0.9, markdown="mineru recovered " * 40)
    parsed = parse_with_optional_ocr(
        digital_backend=digital,
        ocr_backend=ocr,
        mineru_backend=mineru,
        pdf_path=Path("note.pdf"),
    )

    assert parsed.ocr_retried is True
    assert parsed.backend_name == "mineru"
    assert mineru.parse_calls == 1
    assert ocr.parse_calls == 1
