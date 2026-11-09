import os
import time
from pathlib import Path

import pytest

from src.parser.backend import (
    BlockType,
    ConfidenceResult,
    FigureRecord,
    TextBlock,
    TextParseResult,
)
from src.parser.isolated_ocr import IsolatedOcrBackend, child_memory_budget_bytes
from src.parser.routing import parse_with_optional_ocr
from src.storage.state import StateStore

MB = 1024 * 1024


def _worker_ok(conn, pdf_path):
    text = TextParseResult(
        blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="ocr text", page=1)],
        raw_output="ocr text",
        source_page_count=1,
    )
    figures = [FigureRecord(figure_id="f1", page=1, section_path=[])]
    conn.send((text, figures, ConfidenceResult(score=0.9, status="PASS", reasons=[])))


def _worker_memory_hog(conn, pdf_path):
    hog = b"x" * (512 * MB)
    time.sleep(30)
    conn.send(hog)


def _worker_hangs(conn, pdf_path):
    time.sleep(30)


def _worker_dies(conn, pdf_path):
    os._exit(9)


def _worker_raises(conn, pdf_path):
    raise ValueError("bad pdf")


def _backend(worker, **kwargs):
    kwargs.setdefault("start_method", "fork")
    kwargs.setdefault("poll_interval_seconds", 0.05)
    return IsolatedOcrBackend(worker=worker, **kwargs)


def test_returns_the_childs_parse_through_the_backend_interface():
    backend = _backend(_worker_ok)
    pdf = Path("doc.pdf")

    text = backend.parse_text(pdf)
    figures = backend.extract_figures(pdf)
    confidence = backend.confidence(text.blocks, figures)

    assert [block.text for block in text.blocks] == ["ocr text"]
    assert [figure.figure_id for figure in figures] == ["f1"]
    assert confidence.status == "PASS"


def test_kills_child_that_exceeds_memory_limit():
    backend = _backend(_worker_memory_hog, memory_limit_mb=256)
    started = time.monotonic()

    with pytest.raises(RuntimeError, match="memory limit"):
        backend.parse_text(Path("doc.pdf"))

    assert time.monotonic() - started < 20  # killed, not left to finish its 30s sleep


def test_kills_child_that_exceeds_time_limit():
    backend = _backend(_worker_hangs, timeout_seconds=1)
    started = time.monotonic()

    with pytest.raises(RuntimeError, match="time limit"):
        backend.parse_text(Path("doc.pdf"))

    assert time.monotonic() - started < 15


def test_reports_child_that_dies_without_a_result():
    backend = _backend(_worker_dies)

    with pytest.raises(RuntimeError, match="exited unexpectedly"):
        backend.parse_text(Path("doc.pdf"))


def test_reports_child_exception_message():
    backend = _backend(_worker_raises)

    with pytest.raises(RuntimeError, match="bad pdf"):
        backend.parse_text(Path("doc.pdf"))


@pytest.mark.parametrize("worker,kwargs", [
    (_worker_memory_hog, {"memory_limit_mb": 256}),
    (_worker_hangs, {"timeout_seconds": 1}),
    (_worker_dies, {}),
])
def test_failure_messages_are_not_treated_as_transient(tmp_path, worker, kwargs):
    # A transient-looking message would make the poller retry the file forever.
    with pytest.raises(RuntimeError) as excinfo:
        _backend(worker, **kwargs).parse_text(Path("doc.pdf"))

    assert not StateStore._is_transient_error(str(excinfo.value))


class _DigitalBackend:
    def parse_text(self, pdf_path):
        return TextParseResult(
            blocks=[TextBlock(block_type=BlockType.PARAGRAPH, text="digital text", page=1)],
            raw_output="digital text",
            source_page_count=3,  # pages 2-3 missing -> triggers the OCR retry
        )

    def extract_figures(self, pdf_path):
        return []

    def confidence(self, blocks, figures):
        return ConfidenceResult(score=0.8, status="PASS", reasons=[])


def test_digital_parse_is_kept_when_the_ocr_child_is_killed():
    parsed = parse_with_optional_ocr(
        digital_backend=_DigitalBackend(),
        ocr_backend=_backend(_worker_memory_hog, memory_limit_mb=256),
        pdf_path=Path("doc.pdf"),
    )

    assert parsed.backend_name == "docling"
    assert parsed.text_result.raw_output == "digital text"
    assert parsed.ocr_retried is False


def test_budget_is_what_is_left_in_the_cgroup_after_parent_and_margin():
    budget = child_memory_budget_bytes(
        explicit_limit_bytes=None,
        cgroup_limit_bytes=4096 * MB,
        parent_rss_bytes=1500 * MB,
        margin_bytes=256 * MB,
    )

    assert budget == 2340 * MB


def test_explicit_limit_wins_over_cgroup_budget():
    budget = child_memory_budget_bytes(
        explicit_limit_bytes=1000 * MB,
        cgroup_limit_bytes=4096 * MB,
        parent_rss_bytes=1500 * MB,
        margin_bytes=256 * MB,
    )

    assert budget == 1000 * MB


def test_no_budget_without_any_limit_source():
    assert (
        child_memory_budget_bytes(
            explicit_limit_bytes=None,
            cgroup_limit_bytes=None,
            parent_rss_bytes=1500 * MB,
            margin_bytes=256 * MB,
        )
        is None
    )
