"""Single-document analysis pipeline."""

from __future__ import annotations

from research_analysis_layer.services.quality import QualityReviewer
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import HydratedParsedDocument, RunItemResult
from research_analysis_layer.services import (
    AgentExecutor,
    AssertionExtractor,
    Chunker,
    EvidenceBuilder,
    GraphUpdater,
    LifecycleService,
    Resolver,
)


class AnalyzeDocumentPipeline:
    """Analyze one hydrated parsed document."""

    def __init__(
        self,
        store: AnalysisStore,
        chunker: Chunker,
        evidence_builder: EvidenceBuilder,
        assertion_extractor: AssertionExtractor,
        resolver: Resolver,
        graph_updater: GraphUpdater,
        lifecycle_service: LifecycleService,
        quality_reviewer: QualityReviewer,
        analysis_version: str,
        agent_executor: AgentExecutor | None = None,
    ):
        self.store = store
        self.chunker = chunker
        self.evidence_builder = evidence_builder
        self.assertion_extractor = assertion_extractor
        self.resolver = resolver
        self.graph_updater = graph_updater
        self.lifecycle_service = lifecycle_service
        self.quality_reviewer = quality_reviewer
        self.analysis_version = analysis_version
        self.agent_executor = agent_executor

    def run(
        self,
        run_id: int,
        parser_updated_at,
        document: HydratedParsedDocument,
        *,
        skip_agents: bool = False,
        selected_agents: list[str] | None = None,
        agent_only: bool = False,
    ) -> RunItemResult:
        if not document.ready_for_analysis:
            return RunItemResult(
                status="skipped_not_ready",
                error_type="document_not_ready",
                error_text="missing document_hash or normalized theme mismatch",
            )

        quality_report = self.quality_reviewer.review(document)
        quality_summary_json = self.quality_reviewer.to_json(quality_report)
        if not quality_report.passed:
            return RunItemResult(
                status="skipped_low_quality",
                error_type="quality_gate_failed",
                error_text=";".join(quality_report.blocking_issues),
                quality_score=quality_report.score,
                quality_summary_json=quality_summary_json,
            )

        chunks = self.chunker.chunk_document(document)
        evidence_units = self.evidence_builder.build_evidence(chunks, document)

        assertions = []
        for chunk in chunks:
            chunk_evidence = [
                item for item in evidence_units if item.chunk_order == chunk.chunk_order
            ]
            assertions.extend(self.assertion_extractor.extract(chunk, chunk_evidence))

        if agent_only:
            graph_result = None
        else:
            nodes = self.resolver.resolve_nodes(assertions)
            edges = self.resolver.resolve_edges(assertions, nodes)
            graph_result = self.graph_updater.apply_resolutions(
                nodes,
                edges,
                run_id=run_id,
                research_id=document.research_id,
                document_hash=document.document_hash,
            )
            self.lifecycle_service.evaluate_temporal_updates(nodes, edges)

            self.store.replace_document_analysis(
                run_id=run_id,
                parser_updated_at=parser_updated_at,
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
            )
            self.store.set_document_analysis_version(
                research_id=document.research_id,
                analysis_version=self.analysis_version,
                run_id=run_id,
            )

        agent_summary = None
        if not skip_agents and self.agent_executor is not None:
            agent_summary = self.agent_executor.execute(
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
                run_id=run_id,
                analysis_version=self.analysis_version,
                selected_agents=selected_agents,
            )
        return RunItemResult(
            status="success",
            chunk_count=len(chunks),
            assertion_count=len(assertions),
            node_upsert_count=graph_result.node_upsert_count if graph_result else 0,
            edge_upsert_count=graph_result.edge_upsert_count if graph_result else 0,
            open_question_count=graph_result.open_question_count if graph_result else 0,
            quality_score=quality_report.score,
            quality_summary_json=quality_summary_json,
            agent_success_count=agent_summary.success_count if agent_summary else 0,
            agent_no_output_count=agent_summary.no_output_count if agent_summary else 0,
            agent_error_count=agent_summary.error_count if agent_summary else 0,
        )
