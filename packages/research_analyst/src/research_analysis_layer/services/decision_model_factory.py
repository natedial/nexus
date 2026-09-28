"""Factory for DecisionModel providers used by the shadow classifier CLI."""

from __future__ import annotations

from research_analysis_layer.config import Settings
from research_analysis_layer.models.decision_models import QUESTION_SET_VERSION
from research_analysis_layer.services.decision_model import DecisionModel
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel
from research_analysis_layer.services.jev_decision_model import (
    DEFAULT_PINNED_MODEL,
    JevDecisionModel,
)
from research_analysis_layer.services.jev_transport import HttpJevTransport


class DecisionModelConfigError(ValueError):
    """Raised when a requested provider cannot be constructed (fail closed)."""


def build_decision_model(
    settings: Settings,
    *,
    provider: str | None = None,
) -> DecisionModel:
    """Build a DecisionModel from Settings / CLI provider selection.

    Defaults to ``fake``. Selecting ``jev`` without credentials/config raises
    ``DecisionModelConfigError`` instead of silently degrading.
    """
    selected = (provider or settings.decision_model_provider or "fake").strip().lower()
    if selected in {"", "fake"}:
        return FakeDecisionModel(question_set_version=QUESTION_SET_VERSION)

    if selected != "jev":
        raise DecisionModelConfigError(
            f"unsupported decision-model provider: {selected!r} "
            "(expected fake or jev)"
        )

    if not settings.jev_enabled:
        raise DecisionModelConfigError(
            "jev provider requested but RESEARCH_ANALYST_JEV_ENABLED is not true"
        )
    api_key = (settings.jev_api_key or "").strip()
    if not api_key:
        raise DecisionModelConfigError(
            "jev provider requested but RESEARCH_ANALYST_JEV_API_KEY is missing"
        )

    model = (settings.jev_model or DEFAULT_PINNED_MODEL).strip() or DEFAULT_PINNED_MODEL
    transport = HttpJevTransport(
        api_key=api_key,
        base_url=settings.jev_base_url,
        timeout_seconds=float(settings.jev_timeout_seconds),
    )
    return JevDecisionModel(
        transport,
        model=model,
        question_set_version=QUESTION_SET_VERSION,
        max_retries=settings.jev_max_retries,
    )
