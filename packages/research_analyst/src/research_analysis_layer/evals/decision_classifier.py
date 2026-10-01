"""Shadow decision classifier over existing AssertionDraft units."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Mapping, Sequence

from research_analysis_layer.evals.decision_question_set import (
    build_questions_for_unit,
    expected_question_ids,
    snapshot_question_set,
)
from research_analysis_layer.models.assertion_models import AssertionDraft
from research_analysis_layer.models.decision_models import (
    ARTIFACT_SCHEMA_VERSION,
    QUESTION_SET_VERSION,
    CoverageStatus,
    DecisionBatch,
    DecisionBatchResult,
    DecisionResult,
    DecisionUnit,
    ShadowClassificationArtifact,
    UnitClassificationRecord,
)
from research_analysis_layer.services.decision_model import DecisionModel


def assertion_unit_id(assertion: AssertionDraft) -> str:
    """Stable classification identity for an AssertionDraft."""
    return f"chunk-{assertion.chunk_order}:assertion-{assertion.assertion_order}"


def build_decision_unit(
    assertion: AssertionDraft,
    *,
    provenance: Mapping[str, Any] | None = None,
    section_context: str | None = None,
    max_text_chars: int = 1200,
) -> DecisionUnit:
    """Convert an AssertionDraft into a source-grounded DecisionUnit."""
    text = assertion.text or assertion.summary_text or ""
    if len(text) > max_text_chars:
        text = text[: max_text_chars - 1] + "…"
    prov: dict[str, Any] = {
        "chunk_order": assertion.chunk_order,
        "assertion_order": assertion.assertion_order,
        "chunk_key": f"chunk-{assertion.chunk_order}",
        "assertion_key": assertion_unit_id(assertion),
    }
    if provenance:
        prov.update(dict(provenance))
    return DecisionUnit(
        unit_id=assertion_unit_id(assertion),
        text=text,
        chunk_order=assertion.chunk_order,
        assertion_order=assertion.assertion_order,
        assertion_type=assertion.assertion_type,
        section_context=section_context,
        provenance=prov,
    )


class ShadowDecisionClassifier:
    """Batch existing assertion units through an injected DecisionModel."""

    def __init__(
        self,
        decision_model: DecisionModel,
        *,
        batch_size: int = 8,
        question_set_version: str = QUESTION_SET_VERSION,
        max_text_chars: int = 1200,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._model = decision_model
        self._batch_size = batch_size
        self._question_set_version = question_set_version
        self._max_text_chars = max_text_chars

    def classify_assertions(
        self,
        assertions: Sequence[AssertionDraft],
        *,
        document_key: str | None = None,
        document_hash: str | None = None,
        shared_context: str = "",
        provenance_by_unit: Mapping[str, Mapping[str, Any]] | None = None,
        section_context_by_unit: Mapping[str, str] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> ShadowClassificationArtifact:
        """Run shadow classification; never writes canonical analysis output."""
        started = time.perf_counter()
        meta = self._model.metadata()
        units = [
            build_decision_unit(
                assertion,
                provenance=(provenance_by_unit or {}).get(assertion_unit_id(assertion)),
                section_context=(section_context_by_unit or {}).get(
                    assertion_unit_id(assertion)
                ),
                max_text_chars=self._max_text_chars,
            )
            for assertion in assertions
        ]
        # Preserve source order explicitly even if later gather shuffles.
        unit_order = [unit.unit_id for unit in units]
        question_set = snapshot_question_set(
            question_set_version=self._question_set_version
        )

        if not units:
            return ShadowClassificationArtifact(
                schema_version=ARTIFACT_SCHEMA_VERSION,
                question_set_version=self._question_set_version,
                question_set=question_set,
                provider=meta.provider_name,
                adapter_version=meta.adapter_version,
                model_version=meta.model_version,
                document_key=document_key,
                document_hash=document_hash,
                units=[],
                batch_results=[],
                incomplete_batch_count=0,
                permanent_error_count=0,
                total_latency_ms=0.0,
                usage={"batches": 0, "units": 0, "questions": 0},
            )

        batches = self._build_batches(
            units,
            document_key=document_key,
            document_hash=document_hash,
            shared_context=shared_context,
            source_metadata=source_metadata or {},
        )
        batch_results: list[DecisionBatchResult] = []
        results_by_unit: dict[str, list[DecisionResult]] = {uid: [] for uid in unit_order}
        missing_by_unit: dict[str, list[str]] = {uid: [] for uid in unit_order}
        batch_id_by_unit: dict[str, str] = {}
        errors_by_unit: dict[str, list[str]] = {uid: [] for uid in unit_order}
        retry_by_unit: dict[str, int] = {uid: 0 for uid in unit_order}
        latency_by_unit: dict[str, float] = {uid: 0.0 for uid in unit_order}
        usage_total: dict[str, float] = {}
        incomplete_batches = 0
        permanent_errors = 0

        for batch in batches:
            result = self._model.classify_batch(batch)
            batch_results.append(result)
            if result.status != "complete":
                incomplete_batches += 1
            if result.provider_error:
                permanent_errors += 1
            self._merge_usage(usage_total, result.usage)

            expected = {
                (q.question_id, q.target_unit_id) for q in batch.questions
            }
            returned = {
                (r.question_id, r.target_unit_id) for r in result.results
            }
            for question_id, unit_id in sorted(expected - returned):
                missing_by_unit.setdefault(unit_id, []).append(question_id)

            for missing_key in result.missing_question_ids:
                if "::" in missing_key:
                    qid, uid = missing_key.split("::", 1)
                    if qid not in missing_by_unit.get(uid, []):
                        missing_by_unit.setdefault(uid, []).append(qid)

            for unit in batch.units:
                batch_id_by_unit[unit.unit_id] = batch.batch_id
                if result.provider_error:
                    errors_by_unit.setdefault(unit.unit_id, []).append(
                        result.provider_error
                    )
                if result.latency_ms is not None:
                    latency_by_unit[unit.unit_id] = (
                        latency_by_unit.get(unit.unit_id, 0.0) + float(result.latency_ms)
                    )
                retry_by_unit[unit.unit_id] = max(
                    retry_by_unit.get(unit.unit_id, 0), result.retry_count
                )

            for item in result.results:
                if item.target_unit_id not in results_by_unit:
                    # Preserve unknown IDs explicitly rather than inventing units.
                    results_by_unit[item.target_unit_id] = []
                    missing_by_unit.setdefault(item.target_unit_id, [])
                    errors_by_unit.setdefault(item.target_unit_id, [])
                    retry_by_unit.setdefault(item.target_unit_id, 0)
                    latency_by_unit.setdefault(item.target_unit_id, 0.0)
                    if item.target_unit_id not in unit_order:
                        unit_order.append(item.target_unit_id)
                results_by_unit[item.target_unit_id].append(item)
                retry_by_unit[item.target_unit_id] = max(
                    retry_by_unit[item.target_unit_id], item.retry_count
                )
                if item.latency_ms is not None:
                    latency_by_unit[item.target_unit_id] += float(item.latency_ms)
                if item.status == "failed":
                    permanent_errors += 1
                    if item.error:
                        errors_by_unit[item.target_unit_id].append(item.error)
                if item.usage:
                    self._merge_usage(usage_total, item.usage)

            for unknown_id in result.unknown_question_ids:
                permanent_errors += 1
                # Attach unknown IDs to the batch via each unit error channel.
                for unit in batch.units:
                    errors_by_unit[unit.unit_id].append(
                        f"unknown question id from provider: {unknown_id}"
                    )

            del expected  # clarity: coverage handled via missing_by_unit
            del returned

        units_by_id = {unit.unit_id: unit for unit in units}
        records: list[UnitClassificationRecord] = []
        for unit_id in unit_order:
            unit = units_by_id.get(unit_id)
            unit_results = results_by_unit.get(unit_id, [])
            missing = list(dict.fromkeys(missing_by_unit.get(unit_id, [])))
            # Also mark questions absent from returned set relative to question set.
            present = {r.question_id for r in unit_results}
            for qid in expected_question_ids():
                if qid not in present and qid not in missing and unit is not None:
                    # Only auto-mark missing when this unit was actually batched.
                    if unit_id in batch_id_by_unit:
                        missing.append(qid)
            coverage = self._coverage_status(unit_results, missing)
            error = "; ".join(dict.fromkeys(errors_by_unit.get(unit_id, []))) or None
            records.append(
                UnitClassificationRecord(
                    unit_id=unit_id,
                    document_key=document_key,
                    document_hash=document_hash,
                    batch_id=batch_id_by_unit.get(unit_id, ""),
                    source_text=unit.text if unit else "",
                    assertion_type=unit.assertion_type if unit else None,
                    provenance=unit.provenance if unit else {},
                    question_set_version=self._question_set_version,
                    provider=meta.provider_name,
                    adapter_version=meta.adapter_version,
                    model_version=meta.model_version,
                    results=unit_results,
                    coverage_status=coverage,
                    missing_question_ids=missing,
                    retry_count=retry_by_unit.get(unit_id, 0),
                    latency_ms=latency_by_unit.get(unit_id) or None,
                    usage={},
                    error=error,
                )
            )

        total_latency = (time.perf_counter() - started) * 1000.0
        usage_total["batches"] = float(len(batches))
        usage_total["units"] = float(len(records))
        usage_total["questions"] = float(
            sum(len(record.results) for record in records)
        )
        return ShadowClassificationArtifact(
            schema_version=ARTIFACT_SCHEMA_VERSION,
            question_set_version=self._question_set_version,
            question_set=question_set,
            provider=meta.provider_name,
            adapter_version=meta.adapter_version,
            model_version=meta.model_version,
            document_key=document_key,
            document_hash=document_hash,
            units=records,
            batch_results=batch_results,
            incomplete_batch_count=incomplete_batches,
            permanent_error_count=permanent_errors,
            total_latency_ms=total_latency,
            usage=usage_total,
        )

    def _build_batches(
        self,
        units: Sequence[DecisionUnit],
        *,
        document_key: str | None,
        document_hash: str | None,
        shared_context: str,
        source_metadata: Mapping[str, Any],
    ) -> list[DecisionBatch]:
        batches: list[DecisionBatch] = []
        for offset in range(0, len(units), self._batch_size):
            chunk = list(units[offset : offset + self._batch_size])
            questions = []
            for unit in chunk:
                questions.extend(
                    build_questions_for_unit(
                        unit, question_set_version=self._question_set_version
                    )
                )
            batch_id = self._batch_id(
                document_key=document_key,
                document_hash=document_hash,
                unit_ids=[unit.unit_id for unit in chunk],
                offset=offset,
            )
            context = shared_context
            section_bits = [
                unit.section_context
                for unit in chunk
                if unit.section_context
            ]
            if section_bits and not context:
                context = "\n".join(dict.fromkeys(section_bits))
            batches.append(
                DecisionBatch(
                    batch_id=batch_id,
                    shared_context=context,
                    units=chunk,
                    questions=questions,
                    document_key=document_key,
                    document_hash=document_hash,
                    source_metadata=dict(source_metadata),
                )
            )
        return batches

    @staticmethod
    def _batch_id(
        *,
        document_key: str | None,
        document_hash: str | None,
        unit_ids: Sequence[str],
        offset: int,
    ) -> str:
        material = "|".join(
            [
                document_key or "",
                document_hash or "",
                str(offset),
                ",".join(unit_ids),
            ]
        )
        digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]
        return f"batch-{offset}-{digest}"

    @staticmethod
    def _coverage_status(
        results: Sequence[DecisionResult],
        missing_question_ids: Sequence[str],
    ) -> CoverageStatus:
        expected = set(expected_question_ids())
        present = {r.question_id for r in results}
        failed = {r.question_id for r in results if r.status == "failed"}
        if missing_question_ids and not present:
            return "missing"
        if failed and not (present - failed):
            return "failed"
        if missing_question_ids or failed or present != expected:
            return "partial"
        return "full"

    @staticmethod
    def _merge_usage(total: dict[str, float], usage: Mapping[str, Any]) -> None:
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0.0) + float(value)
