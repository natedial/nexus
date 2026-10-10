"""Regression: RoundExecutor._json_safe must not recurse on MagicMock."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from pydantic import BaseModel

from research_analysis_layer.services.round_executor import RoundExecutor


class _TinyModel(BaseModel):
    label: str
    score: float = 0.5


def test_json_safe_does_not_recurse_on_magicmock() -> None:
    mock = MagicMock(chunk_order=0, content="chunk")
    # Pre-fix hasattr(model_dump) path recursed until OOM (multi-GB RSS).
    result = RoundExecutor._json_safe(mock)
    assert result is mock


def test_json_safe_serializes_basemodel_and_namespace() -> None:
    payload = RoundExecutor._json_safe(
        {
            "model": _TinyModel(label="ok"),
            "ns": SimpleNamespace(claim="assertion"),
            "items": (1, "two"),
        }
    )
    assert payload["model"] == {"label": "ok", "score": 0.5}
    assert payload["ns"] == {"claim": "assertion"}
    assert payload["items"] == [1, "two"]
