"""Fake DecisionModel: fail-closed shape→pattern mapping for offline tests."""

from __future__ import annotations

import time
from typing import Any, Callable

from src.graphic_selection.eligibility import eligibility_flags, map_shape_to_pattern
from src.graphic_selection.models import (
    QUESTION_SET_VERSION,
    AnswerDistribution,
    DecisionBatch,
    DecisionBatchResult,
    DecisionModelMetadata,
    DecisionQuestion,
    DecisionResult,
    DecisionUnit,
)
from src.graphic_selection.question_set import (
    PATTERN_OPTIONS,
    REPRESENTATION_QUESTION_ID,
)

FakeResponder = Callable[[DecisionBatch, DecisionQuestion, DecisionUnit], DecisionResult | None]


class FakeDecisionModel:
    """Deterministic in-process adapter with no provider I/O.

    Default Choice uses shape_preference + required-field gate (fail closed to
    prose). Nouls use deterministic eligibility flags. Tests can inject scripted
    responses via ``responses`` / ``fail_question_ids`` / ``drop_question_ids``.
    """

    ADAPTER_VERSION = "fake-graphic-decision-model-v1"

    def __init__(
        self,
        *,
        model_version: str = "fake-1.0.0",
        question_set_version: str = QUESTION_SET_VERSION,
        noul_threshold: float = 0.55,
        responses: dict[tuple[str, str], DecisionResult] | None = None,
        fail_question_ids: set[str] | None = None,
        drop_question_ids: set[str] | None = None,
        unknown_question_ids: list[str] | None = None,
        batch_error: str | None = None,
        latency_ms: float = 1.0,
        responder: FakeResponder | None = None,
    ) -> None:
        self._model_version = model_version
        self._question_set_version = question_set_version
        self._noul_threshold = noul_threshold
        self._responses = responses or {}
        self._fail_question_ids = fail_question_ids or set()
        self._drop_question_ids = drop_question_ids or set()
        self._unknown_question_ids = list(unknown_question_ids or [])
        self._batch_error = batch_error
        self._latency_ms = latency_ms
        self._responder = responder

    def metadata(self) -> DecisionModelMetadata:
        return DecisionModelMetadata(
            provider_name="fake",
            model_version=self._model_version,
            question_set_version=self._question_set_version,
            adapter_version=self.ADAPTER_VERSION,
        )

    def classify_batch(self, batch: DecisionBatch) -> DecisionBatchResult:
        started = time.perf_counter()
        meta = self.metadata()
        if self._batch_error:
            return DecisionBatchResult(
                batch_id=batch.batch_id,
                status="failed",
                results=[],
                metadata=meta,
                missing_question_ids=[self._question_key(q) for q in batch.questions],
                retry_count=0,
                latency_ms=self._latency_ms,
                provider_error=self._batch_error,
            )

        units_by_id = {unit.unit_id: unit for unit in batch.units}
        results: list[DecisionResult] = []
        missing: list[str] = []
        expected_keys = {self._question_key(q) for q in batch.questions}

        for question in batch.questions:
            key = self._question_key(question)
            if question.question_id in self._drop_question_ids:
                missing.append(key)
                continue
            if question.question_id in self._fail_question_ids:
                results.append(
                    DecisionResult(
                        question_id=question.question_id,
                        target_unit_id=question.target_unit_id,
                        status="failed",
                        provider=meta.provider_name,
                        model_version=meta.model_version,
                        error="scripted permanent failure",
                        latency_ms=self._latency_ms,
                    )
                )
                continue

            scripted = self._responses.get((question.question_id, question.target_unit_id))
            if scripted is not None:
                results.append(scripted.model_copy(deep=True))
                continue

            unit = units_by_id.get(question.target_unit_id)
            if unit is None:
                results.append(
                    DecisionResult(
                        question_id=question.question_id,
                        target_unit_id=question.target_unit_id,
                        status="failed",
                        provider=meta.provider_name,
                        model_version=meta.model_version,
                        error=f"unknown target unit: {question.target_unit_id}",
                        latency_ms=self._latency_ms,
                    )
                )
                continue

            if self._responder is not None:
                custom = self._responder(batch, question, unit)
                if custom is not None:
                    results.append(custom)
                    continue

            results.append(self._default_result(question, unit, meta))

        returned_keys = {f"{r.question_id}::{r.target_unit_id}" for r in results}
        for key in sorted(expected_keys - returned_keys):
            if key not in missing:
                missing.append(key)

        unknown = list(self._unknown_question_ids)
        if missing or any(r.status == "failed" for r in results) or unknown:
            status = "partial" if results else "failed"
        else:
            status = "complete"

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return DecisionBatchResult(
            batch_id=batch.batch_id,
            status=status,
            results=results,
            metadata=meta,
            missing_question_ids=missing,
            unknown_question_ids=unknown,
            retry_count=0,
            latency_ms=max(self._latency_ms, elapsed_ms),
        )

    def _default_result(
        self,
        question: DecisionQuestion,
        unit: DecisionUnit,
        meta: DecisionModelMetadata,
    ) -> DecisionResult:
        if question.question_kind == "choice":
            return self._choice_result(question, unit, meta)
        return self._noul_result(question, unit, meta)

    def _choice_result(
        self,
        question: DecisionQuestion,
        unit: DecisionUnit,
        meta: DecisionModelMetadata,
    ) -> DecisionResult:
        selected = map_shape_to_pattern(unit.data_shape, unit.available_fields)
        options = question.options or list(PATTERN_OPTIONS)
        if selected not in options:
            selected = "prose"
        confidence = 0.78 if selected != "prose" else 0.66
        if unit.data_shape in {"", "none"}:
            confidence = 0.9
        remainder = (1.0 - confidence) / max(1, len(options) - 1)
        probs = {
            option: (confidence if option == selected else remainder)
            for option in options
        }
        status = "complete"
        if selected == "prose" and unit.data_shape not in {"", "none"}:
            # Prefer prose when fields missing — still a complete decision.
            status = "complete"
        return DecisionResult(
            question_id=question.question_id,
            target_unit_id=question.target_unit_id,
            status=status,
            distribution=AnswerDistribution(
                probabilities=probs,
                selected=selected,
                raw_probability=confidence,
                calibrated_probability=None,
            ),
            raw_provider_payload={
                "fake": True,
                "data_shape": unit.data_shape,
                "available_fields": list(unit.available_fields),
                "mapped": selected,
            },
            provider=meta.provider_name,
            model_version=meta.model_version,
            latency_ms=self._latency_ms,
        )

    def _noul_result(
        self,
        question: DecisionQuestion,
        unit: DecisionUnit,
        meta: DecisionModelMetadata,
    ) -> DecisionResult:
        flags = unit.eligibility or eligibility_flags(
            unit.data_shape, unit.available_fields
        )
        positive = bool(flags.get(question.question_id, False))
        yes_p = 0.84 if positive else 0.16
        selected = "yes" if yes_p >= self._noul_threshold else "no"
        status = "complete"
        if 0.45 <= yes_p <= 0.55:
            selected = "uncertain"
            status = "uncertain"
        return DecisionResult(
            question_id=question.question_id,
            target_unit_id=question.target_unit_id,
            status=status,
            distribution=AnswerDistribution(
                probabilities={"yes": yes_p, "no": 1.0 - yes_p},
                selected=selected,
                raw_probability=yes_p,
                calibrated_probability=None,
            ),
            raw_provider_payload={"fake": True, "yes": yes_p},
            provider=meta.provider_name,
            model_version=meta.model_version,
            latency_ms=self._latency_ms,
        )

    @staticmethod
    def _question_key(question: DecisionQuestion) -> str:
        return f"{question.question_id}::{question.target_unit_id}"


def scripted_result(
    *,
    question_id: str,
    target_unit_id: str,
    status: str,
    selected: str | None = None,
    probabilities: dict[str, float] | None = None,
    raw_probability: float | None = None,
    error: str | None = None,
    raw_provider_payload: dict[str, Any] | None = None,
) -> DecisionResult:
    """Helper for tests that need an explicit DecisionResult."""
    distribution = None
    if probabilities is not None:
        distribution = AnswerDistribution(
            probabilities=probabilities,
            selected=selected,
            raw_probability=raw_probability,
            calibrated_probability=None,
        )
    return DecisionResult(
        question_id=question_id,
        target_unit_id=target_unit_id,
        status=status,  # type: ignore[arg-type]
        distribution=distribution,
        raw_provider_payload=raw_provider_payload,
        provider="fake",
        model_version="fake-1.0.0",
        error=error,
    )


__all__ = [
    "FakeDecisionModel",
    "FakeResponder",
    "REPRESENTATION_QUESTION_ID",
    "scripted_result",
]
