"""Jev adapter implementing the provider-neutral DecisionModel contract."""

from __future__ import annotations

import time
from typing import Any

from research_analysis_layer.models.decision_models import (
    QUESTION_SET_VERSION,
    AnswerDistribution,
    DecisionBatch,
    DecisionBatchResult,
    DecisionModelMetadata,
    DecisionQuestion,
    DecisionResult,
    DecisionUnit,
)
from research_analysis_layer.services.jev_transport import (
    JevTransport,
    JevTransportError,
)

ADAPTER_VERSION = "jev-decision-model-v1"
DEFAULT_PINNED_MODEL = "jev-1.13.0"
_KEY_SEP = "::"


class JevDecisionModel:
    """Translate DecisionBatch <-> TypeSafe System One without leaking Jev types.

    Transport is injected so adapter tests never need network access. Missing or
    failed answers become explicit failed/uncertain results — never synthetic
    all-negative classifications.
    """

    def __init__(
        self,
        transport: JevTransport,
        *,
        model: str = DEFAULT_PINNED_MODEL,
        question_set_version: str = QUESTION_SET_VERSION,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.25,
        noul_uncertain_low: float = 0.45,
        noul_uncertain_high: float = 0.55,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._transport = transport
        self._model = model
        self._question_set_version = question_set_version
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._noul_uncertain_low = noul_uncertain_low
        self._noul_uncertain_high = noul_uncertain_high

    def metadata(self) -> DecisionModelMetadata:
        return DecisionModelMetadata(
            provider_name="jev",
            model_version=self._model,
            question_set_version=self._question_set_version,
            adapter_version=ADAPTER_VERSION,
        )

    def classify_batch(self, batch: DecisionBatch) -> DecisionBatchResult:
        started = time.perf_counter()
        meta = self.metadata()
        expected_keys = [self._answer_key(q) for q in batch.questions]
        if not batch.questions:
            return DecisionBatchResult(
                batch_id=batch.batch_id,
                status="complete",
                results=[],
                metadata=meta,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                usage={},
            )

        request_body = self._build_request(batch)
        retries = 0
        last_error: str | None = None
        response_body: dict[str, Any] | None = None

        while True:
            try:
                transport_response = self._transport.post_systemone(request_body)
                response_body = transport_response.body
                break
            except JevTransportError as exc:
                last_error = str(exc)
                if exc.retryable and retries < self._max_retries:
                    retries += 1
                    time.sleep(self._retry_backoff_seconds * retries)
                    continue
                return DecisionBatchResult(
                    batch_id=batch.batch_id,
                    status="failed",
                    results=[],
                    metadata=meta,
                    missing_question_ids=expected_keys,
                    retry_count=retries,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    provider_error=last_error,
                )

        assert response_body is not None
        resolved_model = str(response_body.get("model") or self._model)
        meta = DecisionModelMetadata(
            provider_name="jev",
            model_version=resolved_model,
            question_set_version=self._question_set_version,
            adapter_version=ADAPTER_VERSION,
        )
        usage = self._normalize_usage(response_body.get("usage"))
        answers = response_body.get("answers")
        if not isinstance(answers, dict):
            return DecisionBatchResult(
                batch_id=batch.batch_id,
                status="failed",
                results=[],
                metadata=meta,
                missing_question_ids=expected_keys,
                retry_count=retries,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                usage=usage,
                provider_error="malformed Jev response: missing answers object",
            )

        results: list[DecisionResult] = []
        seen: set[str] = set()
        unknown: list[str] = []
        for raw_key, raw_answer in answers.items():
            key = str(raw_key)
            if key not in expected_keys:
                unknown.append(key)
                continue
            question = self._question_for_key(batch.questions, key)
            if question is None:
                unknown.append(key)
                continue
            seen.add(key)
            results.append(
                self._parse_answer(
                    question=question,
                    raw_answer=raw_answer if isinstance(raw_answer, dict) else None,
                    resolved_model=resolved_model,
                    raw_provider_payload={
                        "answer_key": key,
                        "answer": raw_answer,
                    },
                )
            )

        missing = [key for key in expected_keys if key not in seen]
        for key in missing:
            question = self._question_for_key(batch.questions, key)
            if question is None:
                continue
            results.append(
                DecisionResult(
                    question_id=question.question_id,
                    target_unit_id=question.target_unit_id,
                    status="failed",
                    provider="jev",
                    model_version=resolved_model,
                    error="missing answer in provider response",
                    raw_provider_payload={"answer_key": key},
                )
            )

        if missing or unknown or any(r.status == "failed" for r in results):
            status = "partial" if results else "failed"
        else:
            status = "complete"

        return DecisionBatchResult(
            batch_id=batch.batch_id,
            status=status,
            results=results,
            metadata=meta,
            missing_question_ids=missing,
            unknown_question_ids=unknown,
            retry_count=retries,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            usage=usage,
            provider_error=None,
        )

    def _build_request(self, batch: DecisionBatch) -> dict[str, Any]:
        units_by_id = {unit.unit_id: unit for unit in batch.units}
        state = {
            "document_key": batch.document_key,
            "document_hash": batch.document_hash,
            "shared_context": batch.shared_context,
            "units": {
                unit.unit_id: {
                    "text": unit.text,
                    "section_context": unit.section_context,
                    "assertion_type": unit.assertion_type,
                    "provenance": unit.provenance,
                }
                for unit in batch.units
            },
        }
        questions: dict[str, Any] = {}
        for question in batch.questions:
            unit = units_by_id.get(question.target_unit_id)
            questions[self._answer_key(question)] = self._encode_question(
                question, unit=unit
            )
        return {
            "state": state,
            "model": self._model,
            "questions": questions,
        }

    def _encode_question(
        self,
        question: DecisionQuestion,
        *,
        unit: DecisionUnit | None,
    ) -> dict[str, Any]:
        unit_ref = question.target_unit_id
        unit_text = unit.text if unit is not None else ""
        base_instructions = {
            "target_unit_id": unit_ref,
            "target_text": unit_text,
            "question": (
                f"Evaluate only the target unit `{unit_ref}`. "
                f"{question.wording}"
            ),
        }
        if question.question_kind == "noul":
            payload: dict[str, Any] = {
                "type": "noul",
                "instructions": base_instructions,
            }
            if question.noul_criteria:
                payload["criteria"] = dict(question.noul_criteria)
            return payload
        criteria = {option: None for option in (question.options or [])}
        return {
            "type": "choice",
            "instructions": base_instructions,
            "criteria": criteria,
        }

    def _parse_answer(
        self,
        *,
        question: DecisionQuestion,
        raw_answer: dict[str, Any] | None,
        resolved_model: str,
        raw_provider_payload: dict[str, Any],
    ) -> DecisionResult:
        if raw_answer is None:
            return DecisionResult(
                question_id=question.question_id,
                target_unit_id=question.target_unit_id,
                status="failed",
                provider="jev",
                model_version=resolved_model,
                error="malformed answer payload",
                raw_provider_payload=raw_provider_payload,
            )

        answer_type = str(raw_answer.get("type") or "").lower()
        try:
            if question.question_kind == "noul":
                distribution, status = self._parse_noul(raw_answer)
            elif question.question_kind == "choice":
                distribution, status = self._parse_choice(
                    raw_answer, options=question.options or []
                )
            else:
                return DecisionResult(
                    question_id=question.question_id,
                    target_unit_id=question.target_unit_id,
                    status="failed",
                    provider="jev",
                    model_version=resolved_model,
                    error=f"unsupported question kind: {question.question_kind}",
                    raw_provider_payload=raw_provider_payload,
                )
        except ValueError as exc:
            return DecisionResult(
                question_id=question.question_id,
                target_unit_id=question.target_unit_id,
                status="failed",
                provider="jev",
                model_version=resolved_model,
                error=str(exc),
                raw_provider_payload=raw_provider_payload,
            )

        if answer_type and answer_type != question.question_kind:
            # Keep the parsed distribution when usable, but flag the mismatch.
            raw_provider_payload = {
                **raw_provider_payload,
                "type_mismatch": {
                    "expected": question.question_kind,
                    "received": answer_type,
                },
            }

        return DecisionResult(
            question_id=question.question_id,
            target_unit_id=question.target_unit_id,
            status=status,
            distribution=distribution,
            raw_provider_payload=raw_provider_payload,
            provider="jev",
            model_version=resolved_model,
        )

    def _parse_noul(
        self, raw_answer: dict[str, Any]
    ) -> tuple[AnswerDistribution, str]:
        if "noul" not in raw_answer:
            raise ValueError("noul answer missing noul field")
        yes_p = float(raw_answer["noul"])
        if yes_p < 0.0 or yes_p > 1.0:
            raise ValueError(f"noul probability out of range: {yes_p}")
        if self._noul_uncertain_low <= yes_p <= self._noul_uncertain_high:
            selected = "uncertain"
            status = "uncertain"
        else:
            selected = "yes" if yes_p >= 0.5 else "no"
            status = "complete"
        return (
            AnswerDistribution(
                probabilities={"yes": yes_p, "no": 1.0 - yes_p},
                selected=selected,
                raw_probability=yes_p,
                calibrated_probability=None,
            ),
            status,
        )

    def _parse_choice(
        self,
        raw_answer: dict[str, Any],
        *,
        options: list[str],
    ) -> tuple[AnswerDistribution, str]:
        probs_raw = raw_answer.get("probabilities")
        if not isinstance(probs_raw, dict) or not probs_raw:
            raise ValueError("choice answer missing probabilities")
        probabilities = {str(k): float(v) for k, v in probs_raw.items()}
        for option in options:
            probabilities.setdefault(option, 0.0)
        total = sum(probabilities.values())
        if total <= 0:
            raise ValueError("choice probabilities sum to zero")
        if abs(total - 1.0) > 1e-3:
            # Normalize mild drift; extreme cases fail.
            if abs(total - 1.0) > 0.05:
                raise ValueError(f"choice probabilities invalid sum: {total}")
            probabilities = {k: v / total for k, v in probabilities.items()}
        selected = raw_answer.get("choice")
        if selected is None:
            selected = max(probabilities.items(), key=lambda item: item[1])[0]
        selected_s = str(selected)
        raw_probability = float(probabilities.get(selected_s, 0.0))
        status = "complete"
        if selected_s in {"other_or_unclear", "none", "uncertain"}:
            status = "uncertain"
        return (
            AnswerDistribution(
                probabilities=probabilities,
                selected=selected_s,
                raw_probability=raw_probability,
                calibrated_probability=None,
            ),
            status,
        )

    @staticmethod
    def _answer_key(question: DecisionQuestion) -> str:
        return f"{question.target_unit_id}{_KEY_SEP}{question.question_id}"

    @staticmethod
    def _question_for_key(
        questions: list[DecisionQuestion], key: str
    ) -> DecisionQuestion | None:
        for question in questions:
            if JevDecisionModel._answer_key(question) == key:
                return question
        return None

    @staticmethod
    def _normalize_usage(usage: Any) -> dict[str, Any]:
        if not isinstance(usage, dict):
            return {}
        out: dict[str, Any] = {}
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = float(value)
        return out
