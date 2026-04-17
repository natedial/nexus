"""Async eval trigger for production capture."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research_analysis_layer.evals.training_capture import TrainingCaptureManager


class EvalTrigger:
    """Fire-and-forget trigger for capturing production agent outputs.

    Uses a single-threaded executor to avoid blocking the pipeline.
    """

    def __init__(self, capture_manager: "TrainingCaptureManager"):
        self._manager = capture_manager
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")

    def fire_async(
        self,
        document_id: str,
        agent_output: dict,
        confidence: float,
    ) -> None:
        """Submit capture task to executor (non-blocking)."""
        self._pool.submit(
            self._manager.capture,
            document_id=document_id,
            input_data={},
            output_data=agent_output,
            metadata={"source": "production"},
            quality={"golden_score": confidence},
        )

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor."""
        self._pool.shutdown(wait=wait)
