"""Factory for DecisionModel providers used by the graphic chooser."""

from __future__ import annotations

import os

from src.graphic_selection.decision_model import DecisionModel
from src.graphic_selection.fake_decision_model import FakeDecisionModel
from src.graphic_selection.jev_decision_model import (
    DEFAULT_PINNED_MODEL,
    JevDecisionModel,
)
from src.graphic_selection.jev_transport import HttpJevTransport
from src.graphic_selection.models import QUESTION_SET_VERSION

ENV_PREFIX = "RESEARCH_DISPATCHER_"


class DecisionModelConfigError(ValueError):
    """Raised when a requested provider cannot be constructed (fail closed)."""


def _env(name: str, default: str | None = None) -> str | None:
    return os.getenv(f"{ENV_PREFIX}{name}", default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def build_decision_model(
    *,
    provider: str | None = None,
) -> DecisionModel:
    """Build a DecisionModel from env / CLI provider selection.

    Defaults to ``fake``. Selecting ``jev`` without credentials/config raises
    ``DecisionModelConfigError`` instead of silently degrading.
    """
    selected = (
        provider or _env("DECISION_MODEL_PROVIDER", "fake") or "fake"
    ).strip().lower()
    if selected in {"", "fake"}:
        return FakeDecisionModel(question_set_version=QUESTION_SET_VERSION)

    if selected != "jev":
        raise DecisionModelConfigError(
            f"unsupported decision-model provider: {selected!r} "
            "(expected fake or jev)"
        )

    if not _env_bool("JEV_ENABLED", False):
        raise DecisionModelConfigError(
            "jev provider requested but RESEARCH_DISPATCHER_JEV_ENABLED is not true"
        )
    api_key = (_env("JEV_API_KEY") or os.getenv("JEV_API_KEY") or "").strip()
    if not api_key:
        raise DecisionModelConfigError(
            "jev provider requested but RESEARCH_DISPATCHER_JEV_API_KEY is missing"
        )

    model = (_env("JEV_MODEL", DEFAULT_PINNED_MODEL) or DEFAULT_PINNED_MODEL).strip()
    transport = HttpJevTransport(
        api_key=api_key,
        base_url=_env("JEV_BASE_URL", "https://api.typesafe.ai") or "https://api.typesafe.ai",
        timeout_seconds=float(_env_int("JEV_TIMEOUT_SECONDS", 30)),
    )
    return JevDecisionModel(
        transport,
        model=model,
        question_set_version=QUESTION_SET_VERSION,
        max_retries=_env_int("JEV_MAX_RETRIES", 2),
    )


__all__ = [
    "DecisionModelConfigError",
    "build_decision_model",
]
