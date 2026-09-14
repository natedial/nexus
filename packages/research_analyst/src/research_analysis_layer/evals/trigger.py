"""Async eval trigger for production capture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from research_analysis_layer.evals.training_capture import TrainingCaptureManager


@dataclass(slots=True)
class CaptureRequest:
    """A typed capture request the trigger forwards to the capture manager."""

    document_id: str
    analysis_version: str
    agent_type: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    metadata: dict[str, Any]
    confidence: float
    quality_signals: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        return f"{self.document_id}:{self.analysis_version}"


class EvalTrigger:
    """Bounded fire-and-forget trigger for capturing production agent outputs."""

    def __init__(
        self,
        capture_manager: "TrainingCaptureManager",
        *,
        max_queue_size: int = 256,
    ):
        self._manager = capture_manager
        self._queue: Queue[CaptureRequest] = Queue(maxsize=max_queue_size)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")
        self._lock = Lock()
        self._dropped = 0

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    def fire(self, request: CaptureRequest) -> bool:
        """Submit a capture; return True if accepted, False if dropped."""
        try:
            self._queue.put_nowait(request)
        except Full:
            with self._lock:
                self._dropped += 1
            return False
        self._pool.submit(self._drain_one)
        return True

    def _drain_one(self) -> None:
        try:
            request = self._queue.get_nowait()
        except Empty:
            return
        try:
            self._manager.capture_request(request)
        finally:
            self._queue.task_done()

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)
