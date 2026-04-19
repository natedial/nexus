"""Single-document analysis pipeline."""

from __future__ import annotations

from research_analysis_layer.services.quality import QualityReviewer
from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models import HydratedParsedDocument, RunItemResult
from research_analysis_layer.services import (
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
        round_executor=None,
        eval_trigger=None,
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
        self.round_executor = round_executor
        self._eval_trigger = eval_trigger

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

        nodes = []
        edges = []
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

        round_summary = None
        if not skip_agents and self.round_executor is not None:
            from research_analysis_layer.services.agent_registry import get_registry

            registry = get_registry()
            rounds = registry.get_rounds()
            from research_analysis_layer.services.round_executor import AgentSpec

            agent_specs = {}
            tool_registry = self.round_executor.tool_registry
            for round_cfg in rounds:
                for agent_name in round_cfg.agents:
                    agent_cfg = registry.get_agent(agent_name)
                    if agent_cfg:
                        tools = []
                        if tool_registry and agent_cfg.tools:
                            for tool_name in agent_cfg.tools:
                                schema = tool_registry.get_schema(tool_name)
                                if schema:
                                    tools.append(schema)
                        agent_specs[agent_name] = AgentSpec(
                            name=agent_name,
                            config=agent_cfg,
                            tools=tools,
                            max_tool_calls=agent_cfg.max_tool_calls,
                            timeout_seconds=agent_cfg.timeout_seconds,
                            retry_count=agent_cfg.retry_count,
                            temperature=agent_cfg.temperature,
                            output_schema=agent_cfg.output_schema,
                        )
            doc_analysis = self.round_executor.run(
                document=document,
                chunks=chunks,
                evidence_units=evidence_units,
                assertions=assertions,
                quality_report=quality_report,
                node_resolutions=nodes,
                edge_resolutions=edges,
                forecast_candidates=[],
                run_id=run_id,
                analysis_version=self.analysis_version,
                rounds=rounds,
                agent_specs=agent_specs,
            )
            if doc_analysis is None:
                return RunItemResult(
                    status="error",
                    chunk_count=len(chunks),
                    assertion_count=len(assertions),
                    node_upsert_count=graph_result.node_upsert_count
                    if graph_result
                    else 0,
                    edge_upsert_count=graph_result.edge_upsert_count
                    if graph_result
                    else 0,
                    open_question_count=graph_result.open_question_count
                    if graph_result
                    else 0,
                    quality_score=quality_report.score,
                    quality_summary_json=quality_summary_json,
                    error_type="agent_no_output",
                    error_text="synthesizer did not produce a valid DocumentAnalysis",
                    agent_no_output_count=1,
                )

            total_input = sum(rt.input_tokens for rt in doc_analysis.round_traces)
            total_output = sum(rt.output_tokens for rt in doc_analysis.round_traces)
            total_tool_calls = sum(
                rt.tool_call_count for rt in doc_analysis.round_traces
            )
            total_duration = sum(rt.duration_ms for rt in doc_analysis.round_traces)
            self.store.write_document_analysis(
                document_key=doc_analysis.document_key,
                research_id=doc_analysis.research_id,
                document_hash=doc_analysis.document_hash,
                analysis_version=doc_analysis.analysis_version,
                run_id=str(doc_analysis.metadata.run_id),
                payload_json=doc_analysis.model_dump_json(),
                thesis=doc_analysis.thesis,
                confidence=doc_analysis.confidence,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                total_tool_calls=total_tool_calls,
                total_duration_ms=total_duration,
            )
            round_summary = doc_analysis

            if self._eval_trigger is not None:
                try:
                    capture_request = self._build_capture_request(
                        document=document,
                        chunks=chunks,
                        evidence_units=evidence_units,
                        assertions=assertions,
                        doc_analysis=doc_analysis,
                    )
                    if capture_request is not None:
                        self._eval_trigger.fire(capture_request)
                except Exception:
                    pass

        return RunItemResult(
            status="success",
            chunk_count=len(chunks),
            assertion_count=len(assertions),
            node_upsert_count=graph_result.node_upsert_count if graph_result else 0,
            edge_upsert_count=graph_result.edge_upsert_count if graph_result else 0,
            open_question_count=graph_result.open_question_count if graph_result else 0,
            quality_score=quality_report.score,
            quality_summary_json=quality_summary_json,
            agent_success_count=0,
            agent_no_output_count=0,
            agent_error_count=0,
        )

    def _build_capture_request(
        self,
        *,
        document,
        chunks,
        evidence_units,
        assertions,
        doc_analysis,
    ):
        from research_analysis_layer.evals.trigger import CaptureRequest
        from research_analysis_layer.services.agent_input_builder import (
            AgentInputBuilder,
        )
        from research_analysis_layer.services.capture_gate import should_capture

        session_id = (
            f"debate:{document.research_id}:{document.document_hash or ''}:"
            f"{self.analysis_version}:{doc_analysis.metadata.run_id}"
        )
        debate_session = self.store.load_debate_session(session_id)

        decision = should_capture(
            {"thesis": doc_analysis.thesis, "confidence": doc_analysis.confidence},
            debate_session,
        )
        if not decision.capture:
            return None

        synthesizer_input = AgentInputBuilder().build(
            agent_type="synthesizer",
            document=document,
            chunks=chunks,
            evidence_units=evidence_units,
            assertions=assertions,
        )

        verdicts = (debate_session or {}).get("verdicts") or []
        accepted_count = sum(
            1
            for v in verdicts
            if str(v.get("verdict_label", "")).lower() == "accepted"
        )

        return CaptureRequest(
            document_id=str(document.document_hash),
            analysis_version=self.analysis_version,
            agent_type="synthesizer",
            input_payload=synthesizer_input,
            output_payload=doc_analysis.model_dump(),
            metadata={
                "model_used": doc_analysis.metadata.model_used,
                "run_id": doc_analysis.metadata.run_id,
                "debate_session_id": session_id,
                "schema_valid": True,
            },
            confidence=float(doc_analysis.confidence),
            quality_signals={
                "forum_accepted_count": accepted_count,
                "gate_reason": decision.reason,
            },
        )

    def shutdown(self) -> None:
        """Clean up resources, including eval trigger executor."""
        if self._eval_trigger is not None:
            self._eval_trigger.shutdown(wait=True)
