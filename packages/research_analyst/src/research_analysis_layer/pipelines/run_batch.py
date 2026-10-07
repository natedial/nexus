"""Batch run pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from research_analysis_layer.config import Settings
from research_analysis_layer.db import AnalysisStore, CalendarDbClient, ParsedDbClient, StateDbReader
from research_analysis_layer.models import ParserStateRecord
from research_analysis_layer.pipelines.analyze_document import AnalyzeDocumentPipeline
from research_analysis_layer.services import Hydrator, QualityReviewer, Selector
from research_analysis_layer.services.backfill import synthesize_state_record

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchRunResult:
    """High-level batch result."""

    run_id: int
    status: str
    document_count: int
    success_count: int
    skipped_count: int
    error_count: int


@dataclass(slots=True)
class BackfillPreviewResult:
    """Preview result for a manual backfill before any writes."""

    candidate_count: int
    ready_to_apply_count: int
    duplicate_count: int
    not_ready_count: int
    low_quality_count: int
    review_required_count: int
    sample_candidates: list[dict[str, object]]


class RunBatchPipeline:
    """Run the deterministic bootstrap analysis batch."""

    def __init__(
        self,
        settings: Settings,
        state_reader: StateDbReader,
        parsed_db_client: ParsedDbClient,
        calendar_db_client: CalendarDbClient,
        store: AnalysisStore,
        selector: Selector,
        hydrator: Hydrator,
        analyze_document: AnalyzeDocumentPipeline,
        quality_reviewer: QualityReviewer,
    ):
        self.settings = settings
        self.state_reader = state_reader
        self.parsed_db_client = parsed_db_client
        self.calendar_db_client = calendar_db_client
        self.store = store
        self.selector = selector
        self.hydrator = hydrator
        self.analyze_document = analyze_document
        self.quality_reviewer = quality_reviewer

    def run(
        self,
        limit: int | None = None,
        *,
        skip_agents: bool = False,
        agents: list[str] | None = None,
    ) -> BatchRunResult:
        watermark = self.store.get_latest_successful_watermark()
        state_rows = self.state_reader.get_successful_since(
            watermark=watermark,
            limit=limit or self.settings.batch_size,
        )
        return self._run_from_state_rows(
            state_rows,
            run_type="cron",
            trigger_source="state.db",
            skip_agents=skip_agents,
            agents=agents,
        )

    def reprocess(
        self,
        *,
        file_id: str | None = None,
        research_id: int | None = None,
        document_hash: str | None = None,
        skip_agents: bool = False,
        agents: list[str] | None = None,
        agent_only: bool = False,
    ) -> BatchRunResult:
        state_rows: list[ParserStateRecord] = []
        if file_id is not None:
            state_rows = self.state_reader.get_by_file_ids([file_id])
        elif research_id is not None:
            doc = self.hydrator.hydrate_by_research_id(research_id)
            if doc is not None:
                state_rows = [synthesize_state_record(doc)]
        elif document_hash is not None:
            doc = self.hydrator.hydrate_by_document_hash(document_hash)
            if doc is not None:
                state_rows = [synthesize_state_record(doc)]
        return self._run_from_state_rows(
            state_rows,
            run_type="manual_reprocess",
            trigger_source="manual",
            skip_agents=skip_agents,
            agents=agents,
            agent_only=agent_only,
        )

    def backfill(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        allow_warnings: bool = False,
        skip_agents: bool = False,
        agents: list[str] | None = None,
    ) -> BatchRunResult:
        documents = self.parsed_db_client.hydrate_search(
            date_from=date_from,
            date_to=date_to,
            source=source,
            limit=limit or self.settings.batch_size,
        )
        state_rows = [synthesize_state_record(document) for document in documents]
        return self._run_from_state_rows(
            state_rows,
            run_type="manual_backfill",
            trigger_source="parsed_research",
            allow_backfill_warnings=allow_warnings,
            skip_agents=skip_agents,
            agents=agents,
        )

    def preview_backfill(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        source: str | None = None,
        limit: int | None = None,
        allow_warnings: bool = False,
    ) -> BackfillPreviewResult:
        documents = self.parsed_db_client.hydrate_search(
            date_from=date_from,
            date_to=date_to,
            source=source,
            limit=limit or self.settings.batch_size,
        )
        ready_to_apply_count = 0
        duplicate_count = 0
        not_ready_count = 0
        low_quality_count = 0
        review_required_count = 0
        sample_candidates: list[dict[str, object]] = []

        for document in documents:
            state_row = synthesize_state_record(document)
            decision = self.selector.decide(
                state_record=state_row,
                document=document,
                store=self.store,
                analysis_version=self.settings.analysis_version,
            )
            quality_report = self.quality_reviewer.review(document)
            outcome = self._classify_backfill_candidate(
                decision_status=decision.status,
                quality_report=quality_report,
                allow_warnings=allow_warnings,
            )
            if outcome == "duplicate":
                duplicate_count += 1
            elif outcome == "not_ready":
                not_ready_count += 1
            elif outcome == "low_quality":
                low_quality_count += 1
            elif outcome == "review_required":
                review_required_count += 1
            else:
                ready_to_apply_count += 1

            if len(sample_candidates) < 10:
                sample_candidates.append(
                    {
                        "file_id": state_row.file_id,
                        "research_id": document.research_id,
                        "document_name": document.document.document_name,
                        "source": document.document.source,
                        "source_date": document.document.source_date,
                        "document_hash": document.document.document_hash,
                        "selection_reason": decision.reason,
                        "preview_outcome": outcome,
                        "quality_score": quality_report.score,
                        "blocking_issues": list(quality_report.blocking_issues),
                        "warnings": list(quality_report.warnings),
                    }
                )

        return BackfillPreviewResult(
            candidate_count=len(documents),
            ready_to_apply_count=ready_to_apply_count,
            duplicate_count=duplicate_count,
            not_ready_count=not_ready_count,
            low_quality_count=low_quality_count,
            review_required_count=review_required_count,
            sample_candidates=sample_candidates,
        )

    def _run_from_state_rows(
        self,
        state_rows: list[ParserStateRecord],
        *,
        run_type: str,
        trigger_source: str,
        allow_backfill_warnings: bool = True,
        skip_agents: bool = False,
        agents: list[str] | None = None,
        agent_only: bool = False,
    ) -> BatchRunResult:
        run = self.store.create_run(
            run_type=run_type,
            trigger_source=trigger_source,
            settings=self.settings,
        )
        max_watermark: datetime | None = None
        try:
            for state_row in state_rows:
                max_watermark = (
                    state_row.updated_at
                    if max_watermark is None or state_row.updated_at > max_watermark
                    else max_watermark
                )
                hydrated = self.hydrator.hydrate_from_state(state_row)
                decision = self.selector.decide(
                    state_record=state_row,
                    document=hydrated,
                    store=self.store,
                    analysis_version=self.settings.analysis_version,
                )
                if (
                    agent_only
                    and hydrated is not None
                    and hydrated.ready_for_analysis
                ):
                    decision = decision.__class__(
                        file_id=decision.file_id,
                        file_name=decision.file_name,
                        selected=True,
                        status="queued",
                        reason="agent_only_reprocess",
                        research_id=hydrated.research_id,
                        document_hash=hydrated.document_hash,
                    )
                self.store.create_run_item(
                    run_id=run.id,
                    file_id=decision.file_id,
                    reason=decision.reason,
                    research_id=decision.research_id,
                    document_hash=decision.document_hash,
                    status=decision.status,
                )
                if not decision.selected:
                    self.store.finalize_run_item(
                        run_id=run.id,
                        file_id=decision.file_id,
                        status=decision.status,
                        research_id=decision.research_id,
                        document_hash=decision.document_hash,
                    )
                    continue
                assert hydrated is not None
                if run_type == "manual_backfill":
                    quality_report = self.quality_reviewer.review(hydrated)
                    quality_summary_json = self.quality_reviewer.to_json(quality_report)
                    if not quality_report.passed:
                        self.store.finalize_run_item(
                            run_id=run.id,
                            file_id=state_row.file_id,
                            status="skipped_low_quality",
                            research_id=hydrated.research_id,
                            document_hash=hydrated.document_hash,
                            quality_score=quality_report.score,
                            quality_summary_json=quality_summary_json,
                            error_type="quality_gate_failed",
                            error_text=";".join(quality_report.blocking_issues),
                        )
                        continue
                    if quality_report.warnings and not allow_backfill_warnings:
                        self.store.finalize_run_item(
                            run_id=run.id,
                            file_id=state_row.file_id,
                            status="skipped_review_required",
                            research_id=hydrated.research_id,
                            document_hash=hydrated.document_hash,
                            quality_score=quality_report.score,
                            quality_summary_json=quality_summary_json,
                            error_type="quality_review_required",
                            error_text=";".join(quality_report.warnings),
                        )
                        continue
                self.store.mark_run_item_processing(
                    run_id=run.id,
                    file_id=state_row.file_id,
                    research_id=hydrated.research_id,
                    document_hash=hydrated.document_hash,
                )
                try:
                    result = self.analyze_document.run(
                        run_id=run.id,
                        parser_updated_at=state_row.updated_at,
                        document=hydrated,
                        skip_agents=skip_agents,
                        selected_agents=agents,
                        agent_only=agent_only,
                    )
                    self.store.finalize_run_item(
                        run_id=run.id,
                        file_id=state_row.file_id,
                        status=result.status,
                        research_id=hydrated.research_id,
                        document_hash=hydrated.document_hash,
                        chunk_count=result.chunk_count,
                        assertion_count=result.assertion_count,
                        node_upsert_count=result.node_upsert_count,
                        edge_upsert_count=result.edge_upsert_count,
                        open_question_count=result.open_question_count,
                        quality_score=result.quality_score,
                        quality_summary_json=result.quality_summary_json,
                        agent_success_count=result.agent_success_count,
                        agent_no_output_count=result.agent_no_output_count,
                        agent_error_count=result.agent_error_count,
                        error_type=result.error_type,
                        error_text=result.error_text,
                    )
                except Exception as exc:  # pragma: no cover - exercised by CLI
                    logger.exception("Document analysis failed", extra={"file_id": state_row.file_id})
                    self.store.finalize_run_item(
                        run_id=run.id,
                        file_id=state_row.file_id,
                        status="error",
                        research_id=hydrated.research_id,
                        document_hash=hydrated.document_hash,
                        error_type="analysis_error",
                        error_text=str(exc),
                    )
            summary = self.store.finalize_run(run.id, selected_watermark=max_watermark)
            return BatchRunResult(
                run_id=run.id,
                status=str(summary["status"]),
                document_count=int(summary["document_count"]),
                success_count=int(summary["success_count"]),
                skipped_count=int(summary["skipped_count"]),
                error_count=int(summary["error_count"]),
            )
        except Exception:
            raise

    @staticmethod
    def _classify_backfill_candidate(
        *,
        decision_status: str,
        quality_report,
        allow_warnings: bool,
    ) -> str:
        if decision_status == "skipped_duplicate":
            return "duplicate"
        if decision_status == "skipped_not_ready":
            return "not_ready"
        if not quality_report.passed:
            return "low_quality"
        if quality_report.warnings and not allow_warnings:
            return "review_required"
        return "ready_to_apply"
