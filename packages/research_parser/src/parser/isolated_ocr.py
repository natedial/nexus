"""Run the Docling OCR retry in a killable child process.

Docling OCR on a long, image-heavy PDF can need more memory than the container
has. In-process that takes the whole service down; here the parent watches the
child and stops it first, so the caller falls back to the digital parse.

Failure messages deliberately carry no numbers (those go to the log): the state
store treats messages containing markers such as "429" or "timeout" as
transient and would retry the file forever.
"""

from __future__ import annotations

import multiprocessing
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import structlog

from .backend import ConfidenceResult, FigureRecord, ParserBackend, TextBlock, TextParseResult

logger = structlog.get_logger()

_MB = 1024 * 1024
_CGROUP_LIMIT_FILES = (
    "/sys/fs/cgroup/memory.max",  # cgroup v2
    "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
)
_CGROUP_UNLIMITED = 1 << 60  # v1 reports a huge number instead of "max"


@dataclass
class _ChildError:
    message: str


def _ocr_worker(conn, pdf_path: Path) -> None:
    """Child entry point: the full OCR parse, sent back over the pipe."""
    from .docling_backend import DoclingBackend

    backend = DoclingBackend(do_ocr=True)
    text = backend.parse_text(pdf_path)
    figures = backend.extract_figures(pdf_path)
    confidence = backend.confidence(text.blocks, figures)
    conn.send((text, figures, confidence))


def _child_main(worker, conn, pdf_path: Path) -> None:
    try:
        worker(conn, pdf_path)
    except Exception as exc:
        conn.send(_ChildError(str(exc)))


def _cgroup_limit_bytes() -> int | None:
    for path in _CGROUP_LIMIT_FILES:
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < _CGROUP_UNLIMITED:
            return int(raw)
    return None


def child_memory_budget_bytes(
    *,
    explicit_limit_bytes: int | None,
    cgroup_limit_bytes: int | None,
    parent_rss_bytes: int,
    margin_bytes: int,
) -> int | None:
    """How much memory the child may use before the parent must stop it.

    Without an explicit limit it is what the container has left once the
    parent's own footprint and a safety margin are set aside, so the child is
    stopped before the kernel's OOM killer picks the service itself.
    """
    if explicit_limit_bytes is not None:
        return explicit_limit_bytes
    if cgroup_limit_bytes is None:
        return None
    return max(cgroup_limit_bytes - parent_rss_bytes - margin_bytes, 0)


def _receive(conn):
    """Next message, or None when nothing is pending or the pipe is closed."""
    if not conn.poll(0):
        return None
    try:
        return conn.recv()
    except EOFError:
        return None


def _tree_rss_bytes(process: psutil.Process) -> int:
    total = 0
    try:
        for proc in [process, *process.children(recursive=True)]:
            try:
                total += proc.memory_info().rss
            except psutil.NoSuchProcess:
                continue
    except psutil.NoSuchProcess:
        pass
    return total


def _kill_tree(process: multiprocessing.process.BaseProcess) -> None:
    if process.pid is not None:
        try:
            for child in psutil.Process(process.pid).children(recursive=True):
                child.kill()
        except psutil.NoSuchProcess:
            pass
    if process.is_alive():
        process.kill()
    process.join(timeout=10)


class IsolatedOcrBackend(ParserBackend):
    """OCR parse in a spawned child that is killed on a memory or time limit.

    The whole parse (text, figures, confidence) runs in one child because
    DoclingBackend.extract_figures relies on state left behind by parse_text.
    The results are cached for the ParserBackend calls that follow.
    """

    def __init__(
        self,
        *,
        memory_limit_mb: int | None = None,
        timeout_seconds: float = 1500,
        margin_mb: int = 256,
        poll_interval_seconds: float = 0.5,
        start_method: str = "spawn",
        worker=_ocr_worker,
    ):
        self._memory_limit_mb = memory_limit_mb
        self._timeout_seconds = timeout_seconds
        self._margin_bytes = margin_mb * _MB
        self._poll_interval_seconds = poll_interval_seconds
        self._start_method = start_method
        self._worker = worker
        self._figures: list[FigureRecord] = []
        self._confidence: ConfidenceResult | None = None

    def parse_text(self, pdf_path: Path) -> TextParseResult:
        context = multiprocessing.get_context(self._start_method)
        parent_conn, child_conn = context.Pipe(duplex=False)
        process = context.Process(
            target=_child_main, args=(self._worker, child_conn, pdf_path), daemon=True
        )
        process.start()
        child_conn.close()
        try:
            text, figures, confidence = self._wait_for_result(process, parent_conn)
        finally:
            _kill_tree(process)
            parent_conn.close()
        self._figures = figures
        self._confidence = confidence
        return text

    def extract_figures(self, pdf_path: Path) -> list[FigureRecord]:
        return self._figures

    def confidence(
        self, blocks: list[TextBlock], figures: list[FigureRecord]
    ) -> ConfidenceResult:
        if self._confidence is None:
            raise RuntimeError("OCR confidence requested before a parse completed")
        return self._confidence

    def _wait_for_result(self, process, conn):
        budget = child_memory_budget_bytes(
            explicit_limit_bytes=(
                self._memory_limit_mb * _MB if self._memory_limit_mb is not None else None
            ),
            cgroup_limit_bytes=_cgroup_limit_bytes(),
            parent_rss_bytes=psutil.Process().memory_info().rss,
            margin_bytes=self._margin_bytes,
        )
        child = psutil.Process(process.pid)
        deadline = time.monotonic() + self._timeout_seconds
        peak_rss = 0

        while True:
            if conn.poll(self._poll_interval_seconds) or not process.is_alive():
                result = _receive(conn)
                if isinstance(result, _ChildError):
                    raise RuntimeError(f"OCR worker failed: {result.message}")
                if result is not None:
                    return result
                # Pipe closed (or the child is gone) with nothing sent.
                logger.warning("OCR worker exited without a result", exit_code=process.exitcode)
                raise RuntimeError("OCR worker exited unexpectedly without a result")
            if time.monotonic() > deadline:
                logger.warning("OCR worker stopped at time limit", seconds=self._timeout_seconds)
                raise RuntimeError("OCR worker exceeded its time limit and was stopped")
            rss = _tree_rss_bytes(child)
            peak_rss = max(peak_rss, rss)
            if budget is not None and rss > budget:
                logger.warning(
                    "OCR worker stopped at memory limit",
                    rss_mb=rss // _MB,
                    budget_mb=budget // _MB,
                    peak_mb=peak_rss // _MB,
                )
                raise RuntimeError("OCR worker exceeded its memory limit and was stopped")
