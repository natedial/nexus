"""Provider-neutral DecisionModel protocol for graphic selection."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.graphic_selection.models import (
    DecisionBatch,
    DecisionBatchResult,
    DecisionModelMetadata,
)


@runtime_checkable
class DecisionModel(Protocol):
    """Sync batch classifier; adapters must not leak provider-specific types."""

    def metadata(self) -> DecisionModelMetadata:
        """Return pinned provider / model / question-set identity."""

    def classify_batch(self, batch: DecisionBatch) -> DecisionBatchResult:
        """Classify all questions in ``batch`` and return normalized results.

        Implementations must:
        - preserve question and unit IDs;
        - retain full distributions when available;
        - mark missing or malformed answers as failed/uncertain, never as
          synthetic negative classifications;
        - surface retryable vs permanent failures via result status and errors.
        """


__all__ = ["DecisionModel"]
