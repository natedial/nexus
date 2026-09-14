"""Analyst batch loader for dispatcher."""

from __future__ import annotations

import json
from pathlib import Path

from .report_models import DispatchBatch


class AnalystBatchClient:
    """Load dispatcher-ready batches exported by research_analyst."""

    def __init__(self, batch_path: str | Path):
        self.batch_path = Path(batch_path)

    def load_batch(self) -> DispatchBatch:
        if not self.batch_path.exists():
            raise FileNotFoundError(f"Analyst batch not found: {self.batch_path}")
        payload = json.loads(self.batch_path.read_text())
        batch = DispatchBatch.from_dict(payload)
        if not batch.batch_key:
            raise ValueError("Analyst batch requires non-empty batch_key")
        return batch
