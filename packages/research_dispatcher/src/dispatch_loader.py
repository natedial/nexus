"""Load analyst dispatch batches for the dispatcher pipeline."""

from __future__ import annotations

from src.analyst_client import AnalystBatchClient


def load_dispatch_documents(
    *,
    analyst_batch_path: str,
) -> tuple[list[dict], object, str]:
    """Load dispatcher input from an analyst dispatch batch file."""
    dispatch_batch = AnalystBatchClient(analyst_batch_path).load_batch()
    return dispatch_batch.to_legacy_records(), dispatch_batch, "analyst_batch"
