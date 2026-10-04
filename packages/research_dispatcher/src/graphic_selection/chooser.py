"""GraphicChooser: DecisionModel + question set → decision record → pattern id."""

from __future__ import annotations

from typing import Sequence

from src.graphic_selection.decision_model import DecisionModel
from src.graphic_selection.eligibility import (
    eligibility_flags,
    pattern_fields_satisfied,
)
from src.graphic_selection.factory import build_decision_model
from src.graphic_selection.kit import kit_required_fields, kit_selector
from src.graphic_selection.models import (
    QUESTION_SET_VERSION,
    ConceptBlock,
    CoverageStatus,
    DecisionBatch,
    DecisionBatchResult,
    DecisionResult,
    DecisionUnit,
    GraphicDecisionRecord,
    GraphicSelectionArtifact,
    UnitGraphicRecord,
)
from src.graphic_selection.question_set import (
    PATTERN_OPTIONS,
    REPRESENTATION_QUESTION_ID,
    build_questions_for_unit,
    snapshot_question_set,
)


def concept_to_unit(block: ConceptBlock) -> DecisionUnit:
    """Convert a concept block into a DecisionUnit with eligibility hints."""
    flags = eligibility_flags(block.data_shape, block.available_fields)
    return DecisionUnit(
        unit_id=block.concept_id,
        text=block.concept_text or "",
        data_shape=block.data_shape or "none",
        available_fields=list(block.available_fields or []),
        eligibility=flags,
        provenance={"notes": block.notes} if block.notes else {},
    )


class GraphicChooser:
    """Run concept blocks through an injected DecisionModel and emit records."""

    def __init__(
        self,
        decision_model: DecisionModel,
        *,
        question_set_version: str = QUESTION_SET_VERSION,
        enforce_field_gate: bool = True,
    ) -> None:
        self._model = decision_model
        self._question_set_version = question_set_version
        self._enforce_field_gate = enforce_field_gate

    def choose(
        self,
        blocks: Sequence[ConceptBlock],
        *,
        document_key: str | None = None,
        batch_id: str = "graphic-batch-1",
    ) -> GraphicSelectionArtifact:
        meta = self._model.metadata()
        question_set = snapshot_question_set(
            question_set_version=self._question_set_version
        )
        if not blocks:
            return GraphicSelectionArtifact(
                question_set_version=self._question_set_version,
                question_set=question_set,
                provider=meta.provider_name,
                adapter_version=meta.adapter_version,
                model_version=meta.model_version,
                document_key=document_key,
                units=[],
                batch_results=[],
            )

        units = [concept_to_unit(block) for block in blocks]
        questions = []
        for unit in units:
            questions.extend(
                build_questions_for_unit(
                    unit, question_set_version=self._question_set_version
                )
            )
        batch = DecisionBatch(
            batch_id=batch_id,
            units=units,
            questions=questions,
            document_key=document_key,
            source_metadata={"concept_count": len(blocks)},
        )
        batch_result = self._model.classify_batch(batch)
        unit_records = self._build_unit_records(
            units=units,
            blocks=blocks,
            batch_result=batch_result,
            meta_provider=meta.provider_name,
            meta_model=meta.model_version,
            meta_adapter=meta.adapter_version,
        )
        return GraphicSelectionArtifact(
            question_set_version=self._question_set_version,
            question_set=question_set,
            provider=meta.provider_name,
            adapter_version=meta.adapter_version,
            model_version=meta.model_version,
            document_key=document_key,
            units=unit_records,
            batch_results=[batch_result],
        )

    def choose_one(self, block: ConceptBlock) -> GraphicDecisionRecord:
        artifact = self.choose([block], batch_id=f"graphic-{block.concept_id}")
        if not artifact.units:
            raise RuntimeError("chooser returned no units")
        return artifact.units[0].decision

    def _build_unit_records(
        self,
        *,
        units: Sequence[DecisionUnit],
        blocks: Sequence[ConceptBlock],
        batch_result: DecisionBatchResult,
        meta_provider: str,
        meta_model: str,
        meta_adapter: str,
    ) -> list[UnitGraphicRecord]:
        results_by_unit: dict[str, list[DecisionResult]] = {
            unit.unit_id: [] for unit in units
        }
        for result in batch_result.results:
            results_by_unit.setdefault(result.target_unit_id, []).append(result)

        blocks_by_id = {block.concept_id: block for block in blocks}
        records: list[UnitGraphicRecord] = []
        for unit in units:
            unit_results = results_by_unit.get(unit.unit_id, [])
            decision, coverage = self._resolve_decision(
                unit=unit,
                results=unit_results,
                batch_failed=batch_result.status == "failed"
                and not batch_result.results,
                provider=meta_provider,
                model_version=meta_model,
                adapter_version=meta_adapter,
            )
            block = blocks_by_id.get(unit.unit_id)
            records.append(
                UnitGraphicRecord(
                    unit_id=unit.unit_id,
                    data_shape=unit.data_shape,
                    available_fields=list(unit.available_fields),
                    decision=decision,
                    results=unit_results,
                    coverage_status=coverage,
                )
            )
            # Keep expected_pattern_id only on fixture ConceptBlock; not on record.
            _ = block
        return records

    def _resolve_decision(
        self,
        *,
        unit: DecisionUnit,
        results: Sequence[DecisionResult],
        batch_failed: bool,
        provider: str,
        model_version: str,
        adapter_version: str,
    ) -> tuple[GraphicDecisionRecord, CoverageStatus]:
        by_qid = {r.question_id: r for r in results}
        choice_result = by_qid.get(REPRESENTATION_QUESTION_ID)

        nouls: dict[str, bool] = {}
        for question_id, result in by_qid.items():
            if question_id == REPRESENTATION_QUESTION_ID:
                continue
            if result.distribution is None:
                nouls[question_id] = False
                continue
            selected = (result.distribution.selected or "no").lower()
            nouls[question_id] = selected == "yes"

        # Prefer model eligibility; fill gaps from deterministic flags.
        for key, value in unit.eligibility.items():
            nouls.setdefault(key, value)

        model_choice = "prose"
        confidence = 0.0
        options_considered = list(PATTERN_OPTIONS)
        coverage: CoverageStatus = "full"

        if batch_failed or choice_result is None or choice_result.status == "failed":
            coverage = "failed" if batch_failed else "missing"
            rationale = "DecisionModel Choice missing or failed; fail closed to prose."
        else:
            if choice_result.distribution is not None:
                selected = choice_result.distribution.selected
                confidence = float(choice_result.distribution.raw_probability or 0.0)
                if selected in PATTERN_OPTIONS:
                    model_choice = selected
                elif selected:
                    model_choice = "prose"
            if choice_result.status == "uncertain":
                coverage = "partial"
            rationale = (
                f"Choice={model_choice} from data_shape={unit.data_shape} "
                f"(provider={provider})."
            )

        emit_pattern = model_choice
        gated = False
        if (
            self._enforce_field_gate
            and emit_pattern != "prose"
            and not pattern_fields_satisfied(emit_pattern, unit.available_fields)
        ):
            gated = True
            rationale = (
                f"Choice={model_choice} failed required-field gate; emit prose."
            )
            emit_pattern = "prose"

        populate_from = (
            kit_required_fields(emit_pattern) if emit_pattern != "prose" else []
        )
        decision = GraphicDecisionRecord(
            question_set_version=self._question_set_version,
            concept_id=unit.unit_id,
            choice={
                "representation": model_choice,
                "options_considered": options_considered,
                "confidence": confidence,
                "field_gated": gated,
            },
            nouls=nouls,
            emit={
                "pattern_id": emit_pattern,
                "fallback": "prose",
                "kit_selector": kit_selector(emit_pattern),
                "populate_from": populate_from,
                "do_not_invent_fields": True,
            },
            rationale_short=rationale,
            provider=provider,
            model_version=model_version,
            adapter_version=adapter_version,
        )
        return decision, coverage


def choose_graphics(
    blocks: Sequence[ConceptBlock],
    *,
    provider: str | None = None,
    decision_model: DecisionModel | None = None,
    document_key: str | None = None,
) -> GraphicSelectionArtifact:
    """Convenience entry: build provider (default fake) and choose patterns."""
    model = decision_model or build_decision_model(provider=provider)
    return GraphicChooser(model).choose(blocks, document_key=document_key)


__all__ = [
    "GraphicChooser",
    "choose_graphics",
    "concept_to_unit",
]
