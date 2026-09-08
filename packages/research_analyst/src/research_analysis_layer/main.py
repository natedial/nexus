"""CLI entrypoint."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys
from urllib.error import HTTPError

_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from research_pipeline_ops import PipelineOpsClient
from research_analysis_layer.config import Settings, resolve_codex_bin
from research_analysis_layer.db import (
    AnalysisStore,
    CalendarDbClient,
    ParsedDbClient,
    StateDbReader,
)
from research_analysis_layer.logging import configure_logging
from research_analysis_layer.pipelines import AnalyzeDocumentPipeline, RunBatchPipeline
from research_analysis_layer.services import (
    AgentInputBuilder,
    AssertionExtractor,
    Chunker,
    ClaimKeyResolver,
    ConsensusClusterer,
    EvidenceBuilder,
    EvidenceReferentResolver,
    distinct_publishers,
    source_diversity,
    ForecastExtractor,
    ForecastMatcher,
    GraphUpdater,
    Hydrator,
    LifecycleService,
    QualityReviewer,
    RawForecastExtractor,
    ReviewHarness,
    Resolver,
    Selector,
    build_agent_llm_client,
)
from research_analysis_layer.services.agent_registry import get_registry
from research_analysis_layer.services.claim_key_resolver import (
    claim_resolution_stats,
    load_claim_golden,
    score_claim_golden,
)
from research_analysis_layer.services.evidence_referent_resolver import (
    load_referent_golden,
    referent_resolution_stats,
    score_referent_golden,
)
from research_analysis_layer.services.reconcile import reconcile_recent
from research_analysis_layer.services.round_executor import RoundExecutor
from research_analysis_layer.services.tools.registry import ToolRegistry
from research_analysis_layer.services.tools.distill_adapter import (
    DistillAdapter,
    create_distill_handlers,
)
from research_analysis_layer.services.tools.tholos_adapter import (
    TholosAdapter,
    create_tholos_handlers,
)

logger = logging.getLogger(__name__)


def build_app(settings: Settings) -> RunBatchPipeline:
    """Construct the bootstrap service graph."""
    state_reader = StateDbReader(settings.state_db_path)
    parsed_db_client = ParsedDbClient(
        base_url=settings.parsed_db_url,
        api_key=settings.parsed_db_key,
        timeout_seconds=settings.request_timeout_seconds,
    )
    calendar_db_client = CalendarDbClient(
        base_url=settings.calendar_db_url,
        api_key=settings.calendar_db_key,
        timeout_seconds=settings.request_timeout_seconds,
        match_source=settings.calendar_match_source,
        source_name=settings.calendar_source_name,
    )
    store = AnalysisStore(settings.analysis_db_path)
    selector = Selector()
    hydrator = Hydrator(parsed_db_client)
    registry = get_registry()

    tool_registry = None
    if settings.analyst_tools_enabled:
        tool_registry = ToolRegistry()

        assert tool_registry.get_schema("research_search") is not None, (
            f"Tool schema not loaded from {tool_registry._schema_path}"
        )

        if settings.tholos_enabled:
            tholos_adapter = TholosAdapter(
                base_url=settings.tholos_base_url,
                timeout_seconds=settings.tholos_timeout_seconds,
            )
            handlers = create_tholos_handlers(tholos_adapter)
        else:
            distill_adapter = DistillAdapter()
            handlers = create_distill_handlers(distill_adapter)

        for name, handler in handlers.items():
            tool_registry.register_handler(name, handler)

    llm_client = build_agent_llm_client(settings, tool_registry)

    round_executor = None
    if (
        settings.analyst_round_mode == "rounds"
        and registry.has_rounds_config()
        and llm_client is not None
    ):
        round_executor = RoundExecutor(
            registry=registry,
            llm_client=llm_client,
            input_builder=AgentInputBuilder(),
            tool_registry=tool_registry,
            analysis_store=store,
            debate_mode=settings.analyst_debate_mode,
            debate_judge_model=settings.analyst_debate_judge_model,
            max_debate_arguments=settings.analyst_max_debate_arguments,
        )

    eval_trigger = None
    if settings.eval_capture_enabled:
        from research_analysis_layer.evals.training_capture import (
            TrainingCaptureManager,
        )
        from research_analysis_layer.evals.trigger import EvalTrigger

        eval_trigger = EvalTrigger(TrainingCaptureManager(settings.eval_captures_dir))
        # Owned by main.py for the process lifetime; pipeline must NOT shut it down.

    analyze_document = AnalyzeDocumentPipeline(
        store=store,
        chunker=Chunker(),
        evidence_builder=EvidenceBuilder(),
        assertion_extractor=AssertionExtractor(),
        resolver=Resolver(),
        graph_updater=GraphUpdater(store),
        lifecycle_service=LifecycleService(store),
        quality_reviewer=QualityReviewer(settings),
        analysis_version=settings.analysis_version,
        round_executor=round_executor,
        eval_trigger=eval_trigger,
        referent_resolver=EvidenceReferentResolver(
            granularity=settings.referent_granularity,
        ),
        claim_resolver=ClaimKeyResolver(),
    )

    ops = PipelineOpsClient.from_env(
        default_spool_db_path=str(
            settings.analysis_db_path.parent / "pipeline_ops_spool.db"
        ),
        emitted_by="research_analyst",
    )
    pipeline = RunBatchPipeline(
        settings=settings,
        state_reader=state_reader,
        parsed_db_client=parsed_db_client,
        calendar_db_client=calendar_db_client,
        store=store,
        selector=selector,
        hydrator=hydrator,
        analyze_document=analyze_document,
        quality_reviewer=QualityReviewer(settings),
        ops=ops,
    )
    pipeline.eval_trigger = eval_trigger
    return pipeline


def _print_eval_trigger_stats(trigger) -> None:
    if trigger is None:
        return
    print(
        f"eval_trigger: queue_depth={trigger.queue_depth} "
        f"dropped={trigger.dropped_count}"
    )


def _print_rollout_stats(round_executor, *, settings: Settings | None = None) -> None:
    if round_executor is None:
        if settings is None:
            return
        print(f"debate_mode={settings.analyst_debate_mode}")
        return
    mode = getattr(round_executor, "debate_mode", "off")
    print(f"debate_mode={mode}")
    if mode == "off":
        return
    stats = round_executor.rollout_stats
    print(
        f"rollout_stats: shadow_runs={stats.shadow_runs_total}, "
        f"shadow_failures={stats.shadow_failures_total}, "
        f"debate_tokens_total={stats.debate_input_tokens + stats.debate_output_tokens}, "
        f"baseline_tokens_total={stats.baseline_input_tokens + stats.baseline_output_tokens}, "
        f"debate_avg_ms={stats.debate_duration_ms // max(1, stats.shadow_runs_total) if stats.shadow_runs_total > 0 else 0}, "
        f"baseline_avg_ms={stats.baseline_duration_ms // max(1, stats.shadow_runs_total) if stats.shadow_runs_total > 0 else 0}"
    )


def _referent_resolution_report(store: AnalysisStore, settings: Settings) -> dict:
    resolver = EvidenceReferentResolver(granularity=settings.referent_granularity)
    try:
        rows = store.list_document_analyses()
    except Exception as exc:  # pragma: no cover - doctor stays up if store is empty/unready
        return {
            "granularity": settings.referent_granularity,
            "error": str(exc),
        }
    payloads = []
    for row in rows:
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(payload)
    stats = referent_resolution_stats(payloads, resolver)
    return stats


def _claim_resolution_report(store: AnalysisStore) -> dict:
    resolver = ClaimKeyResolver()
    try:
        rows = store.list_document_analyses()
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    payloads = [
        row["payload_json"]
        for row in rows
        if isinstance(row.get("payload_json"), dict)
    ]
    return claim_resolution_stats(payloads, resolver)


def _publisher_diversity_report(store: AnalysisStore) -> dict:
    try:
        docs = store.list_analyzed_documents()
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    publishers = distinct_publishers(docs)
    return {
        "document_count": len(docs),
        "source_diversity": source_diversity(docs),
        "publishers": [item.label for item in publishers],
    }


def _consensus_report(store: AnalysisStore, settings: Settings) -> dict:
    try:
        maps = store.list_argument_maps_for_consensus()
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    snapshot = ConsensusClusterer(
        min_publishers=settings.consensus_min_publishers
    ).cluster_maps(maps)
    return {
        "min_publishers": snapshot.min_publishers,
        "clustered_claim_count": snapshot.clustered_claim_count,
        "skipped_unresolved_count": snapshot.skipped_unresolved_count,
        "agreement_count": len(snapshot.agreements),
        "disagreement_count": len(snapshot.disagreements),
        "agreements": [item.point for item in snapshot.agreements],
        "disagreements": [item.point for item in snapshot.disagreements],
    }


def _write_resolved_payloads(store: AnalysisStore, rows: list[dict], mutate) -> int:
    updated = 0
    for row in rows:
        payload = row.get("payload_json")
        if not isinstance(payload, dict):
            continue
        mutate(payload)
        store.write_document_analysis(
            document_key=str(row["document_key"]),
            research_id=int(row["research_id"]),
            document_hash=str(row["document_hash"]),
            analysis_version=str(row["analysis_version"]),
            run_id=str(row["run_id"]),
            payload_json=json.dumps(payload, sort_keys=True),
            thesis=row.get("thesis") if isinstance(row.get("thesis"), str) else None,
            confidence=(
                float(row["confidence"]) if row.get("confidence") is not None else None
            ),
            total_input_tokens=int(row.get("total_input_tokens") or 0),
            total_output_tokens=int(row.get("total_output_tokens") or 0),
            total_tool_calls=int(row.get("total_tool_calls") or 0),
            total_duration_ms=int(row.get("total_duration_ms") or 0),
        )
        updated += 1
    return updated


def command_resolve_referents(
    settings: Settings,
    *,
    golden: str | None,
    apply: bool,
    limit: int | None,
    granularity: str | None,
) -> int:
    """Score the referent golden set and optionally backfill stored maps."""
    resolved_granularity = (
        granularity or settings.referent_granularity or "coarse"
    ).strip().lower()
    resolver = EvidenceReferentResolver(granularity=resolved_granularity)
    golden_path = Path(golden) if golden else (
        Path(__file__).resolve().parents[2] / "evals" / "golden" / "referents.jsonl"
    )
    report: dict[str, object] = {
        "granularity": resolver.granularity,
        "golden_path": str(golden_path),
    }
    if golden_path.exists():
        rows = load_referent_golden(golden_path)
        report["golden"] = score_referent_golden(rows, resolver)
    else:
        report["golden"] = {"error": f"golden set not found: {golden_path}"}

    store = AnalysisStore(settings.analysis_db_path)
    stored_rows = store.list_document_analyses(limit=limit)
    payloads = []
    for row in stored_rows:
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(payload)
    report["store"] = referent_resolution_stats(payloads, resolver)
    report["apply"] = apply
    updated = 0
    if apply:
        for row in stored_rows:
            payload = row.get("payload_json")
            if not isinstance(payload, dict):
                continue
            resolver.resolve_payload(payload)
            store.write_document_analysis(
                document_key=str(row["document_key"]),
                research_id=int(row["research_id"]),
                document_hash=str(row["document_hash"]),
                analysis_version=str(row["analysis_version"]),
                run_id=str(row["run_id"]),
                payload_json=json.dumps(payload, sort_keys=True),
                thesis=row.get("thesis") if isinstance(row.get("thesis"), str) else None,
                confidence=(
                    float(row["confidence"]) if row.get("confidence") is not None else None
                ),
                total_input_tokens=int(row.get("total_input_tokens") or 0),
                total_output_tokens=int(row.get("total_output_tokens") or 0),
                total_tool_calls=int(row.get("total_tool_calls") or 0),
                total_duration_ms=int(row.get("total_duration_ms") or 0),
            )
            updated += 1
        report["updated_rows"] = updated
        report["store_after"] = referent_resolution_stats(
            [
                row["payload_json"]
                for row in store.list_document_analyses(limit=limit)
                if isinstance(row.get("payload_json"), dict)
            ],
            resolver,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    golden_report = report.get("golden")
    if isinstance(golden_report, dict) and golden_report.get("false_merges"):
        return 1
    return 0


def command_resolve_claims(
    settings: Settings,
    *,
    golden: str | None,
    apply: bool,
    limit: int | None,
) -> int:
    """Score the claim golden set and optionally backfill stored maps."""
    resolver = ClaimKeyResolver()
    golden_path = Path(golden) if golden else (
        Path(__file__).resolve().parents[2] / "evals" / "golden" / "claims.jsonl"
    )
    report: dict[str, object] = {"golden_path": str(golden_path)}
    if golden_path.exists():
        report["golden"] = score_claim_golden(load_claim_golden(golden_path), resolver)
    else:
        report["golden"] = {"error": f"golden set not found: {golden_path}"}

    store = AnalysisStore(settings.analysis_db_path)
    stored_rows = store.list_document_analyses(limit=limit)
    payloads = [
        row["payload_json"]
        for row in stored_rows
        if isinstance(row.get("payload_json"), dict)
    ]
    report["store"] = claim_resolution_stats(payloads, resolver)
    report["apply"] = apply
    if apply:
        report["updated_rows"] = _write_resolved_payloads(
            store, stored_rows, resolver.resolve_payload
        )
        report["store_after"] = claim_resolution_stats(
            [
                row["payload_json"]
                for row in store.list_document_analyses(limit=limit)
                if isinstance(row.get("payload_json"), dict)
            ],
            resolver,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    golden_report = report.get("golden")
    if isinstance(golden_report, dict) and golden_report.get("false_merges"):
        return 1
    return 0


def command_consensus(
    settings: Settings,
    *,
    min_publishers: int | None,
    limit: int | None,
) -> int:
    """Cluster stored argument maps into consensus and divergence points."""
    n = min_publishers if min_publishers is not None else settings.consensus_min_publishers
    store = AnalysisStore(settings.analysis_db_path)
    maps = store.list_argument_maps_for_consensus(limit=limit)
    snapshot = ConsensusClusterer(min_publishers=n).cluster_maps(maps)
    print(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True))
    return 0


def command_doctor(settings: Settings) -> int:
    """Run basic environment and connectivity checks."""
    errors = settings.validate()
    pipeline = build_app(settings)
    state_counts = (
        pipeline.state_reader.get_status_counts()
        if settings.state_db_path.exists()
        else {}
    )
    parsed_ok, parsed_message = pipeline.parsed_db_client.check_connection()
    calendar_ok, calendar_message = pipeline.calendar_db_client.check_connection()
    analysis_counts = pipeline.store.get_analysis_counts()
    registry = get_registry()
    prompt_status = {}
    for agent_name in registry.get_agent_names():
        prompt_status[agent_name] = registry.resolve_prompt_path(agent_name) is not None
    report = {
        "config_errors": errors,
        "state_db_exists": settings.state_db_path.exists(),
        "state_counts": state_counts,
        "parsed_db_ok": parsed_ok,
        "parsed_db_message": parsed_message,
        "calendar_db_ok": calendar_ok,
        "calendar_db_message": calendar_message,
        "calendar_match_source": settings.calendar_match_source,
        "calendar_source_name": settings.calendar_source_name,
        "analysis_store_path": str(settings.analysis_db_path),
        "analysis_store_counts": analysis_counts,
        "agent_execution": {
            "enabled": settings.agent_execution_enabled,
            "provider": settings.agent_llm_provider,
            "codex_bin": (
                resolve_codex_bin(settings.agent_llm_codex_bin)
                if (settings.agent_llm_provider or "").strip().lower() == "codex"
                else None
            ),
            "configured_agent_count": len(registry.get_agent_names()),
            "prompt_resolution": prompt_status,
        },
        "quality_gate": {
            "min_full_text_chars": settings.min_full_text_chars,
            "min_quality_score": settings.min_quality_score,
            "min_usable_theme_ratio": settings.min_usable_theme_ratio,
            "backfill_require_warning_free": settings.backfill_require_warning_free,
        },
        "referent_resolution": _referent_resolution_report(pipeline.store, settings),
        "claim_resolution": _claim_resolution_report(pipeline.store),
        "publisher_diversity": _publisher_diversity_report(pipeline.store),
        "consensus": _consensus_report(pipeline.store, settings),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    _print_eval_trigger_stats(pipeline.eval_trigger)
    _print_rollout_stats(pipeline.analyze_document.round_executor, settings=settings)
    prompt_ok = (
        all(prompt_status.values())
        if settings.agent_execution_enabled and prompt_status
        else True
    )
    return 0 if not errors and parsed_ok and calendar_ok and prompt_ok else 1


def command_run(
    settings: Settings,
    limit: int | None,
    *,
    skip_agents: bool,
    agents: list[str] | None,
) -> int:
    pipeline = build_app(settings)
    try:
        result = pipeline.run(
            limit=limit,
            skip_agents=skip_agents,
            agents=agents,
        )
    finally:
        if pipeline.eval_trigger is not None:
            pipeline.eval_trigger.shutdown(wait=True)
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.error_count == 0 else 1


def command_reprocess(
    settings: Settings,
    file_id: str | None,
    research_id: int | None,
    document_hash: str | None,
    *,
    skip_agents: bool,
    agents: list[str] | None,
    agent_only: bool,
) -> int:
    pipeline = build_app(settings)
    result = pipeline.reprocess(
        file_id=file_id,
        research_id=research_id,
        document_hash=document_hash,
        skip_agents=skip_agents,
        agents=agents,
        agent_only=agent_only,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.error_count == 0 else 1


def command_backfill(
    settings: Settings,
    *,
    date_from: str | None,
    date_to: str | None,
    source: str | None,
    limit: int | None,
    apply: bool,
    allow_warnings: bool,
    skip_agents: bool,
    agents: list[str] | None,
) -> int:
    pipeline = build_app(settings)
    if not apply:
        preview = pipeline.preview_backfill(
            date_from=date_from,
            date_to=date_to,
            source=source,
            limit=limit,
            allow_warnings=allow_warnings,
        )
        print(json.dumps(asdict(preview), indent=2, sort_keys=True))
        return 0
    result = pipeline.backfill(
        date_from=date_from,
        date_to=date_to,
        source=source,
        limit=limit,
        allow_warnings=allow_warnings,
        skip_agents=skip_agents,
        agents=agents,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.error_count == 0 else 1


def command_reconcile(settings: Settings, limit: int) -> int:
    pipeline = build_app(settings)
    result = reconcile_recent(
        state_reader=pipeline.state_reader,
        parsed_db_client=pipeline.parsed_db_client,
        store=pipeline.store,
        analysis_version=settings.analysis_version,
        limit=limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["missing_parsed_documents"] == 0 else 1


def command_extract_forecasts(
    settings: Settings,
    *,
    limit: int | None,
    research_id: int | None,
    rebuild: bool,
    dry_run: bool,
) -> int:
    pipeline = build_app(settings)
    report = _extract_forecasts_report(
        pipeline,
        limit=limit,
        research_id=research_id,
        rebuild=rebuild,
        dry_run=dry_run,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def command_review_forecasts(
    settings: Settings,
    *,
    review_status: str | None,
    upload_status: str | None,
    limit: int | None,
) -> int:
    pipeline = build_app(settings)
    candidates = pipeline.store.list_forecast_candidates(
        review_status=review_status,
        upload_status=upload_status,
        limit=limit,
    )
    summary = {
        "candidate_count": len(candidates),
        "review_status": review_status,
        "upload_status": upload_status,
        "sample_candidates": [asdict(candidate) for candidate in candidates[:20]],
    }
    pipeline.store.save_review_snapshot(
        review_scope="forecast_candidates",
        review_key=f"{review_status or 'all'}:{upload_status or 'all'}",
        payload=summary,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def command_set_forecast_review(
    settings: Settings,
    *,
    candidate_ids: list[int],
    review_status: str,
    review_notes: str | None,
) -> int:
    pipeline = build_app(settings)
    updated = pipeline.store.update_forecast_review_status(
        candidate_ids=candidate_ids,
        review_status=review_status,
        review_notes=review_notes,
    )
    report = {
        "candidate_ids": candidate_ids,
        "review_status": review_status,
        "review_notes": review_notes,
        "updated_count": updated,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def command_upload_forecasts(
    settings: Settings,
    *,
    limit: int | None,
) -> int:
    pipeline = build_app(settings)
    report = _upload_forecasts_report(pipeline, limit=limit)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["failed_count"] == 0 else 1


def command_sync_forecasts(
    settings: Settings,
    *,
    extract_limit: int | None,
    upload_limit: int | None,
) -> int:
    pipeline = build_app(settings)
    extract_report = _extract_forecasts_report(
        pipeline,
        limit=extract_limit,
        research_id=None,
        rebuild=False,
        dry_run=False,
    )
    upload_report = _upload_forecasts_report(pipeline, limit=upload_limit)
    report = {
        "extract": extract_report,
        "upload": upload_report,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if upload_report["failed_count"] == 0 else 1


def _extract_forecasts_report(
    pipeline: RunBatchPipeline,
    *,
    limit: int | None,
    research_id: int | None,
    rebuild: bool,
    dry_run: bool,
) -> dict[str, object]:
    extractor = ForecastExtractor()
    matcher = ForecastMatcher()
    raw_extractor = RawForecastExtractor()
    deleted_count = 0
    if rebuild and not dry_run:
        deleted_count = pipeline.store.delete_forecast_candidates(
            research_id=research_id
        )
    assertion_sources = pipeline.store.get_forecast_extraction_sources(
        limit=limit,
        research_id=research_id,
        only_missing=not rebuild,
    )
    candidates = []
    for source in assertion_sources:
        extracted = extractor.extract(source)
        for candidate in extracted:
            candidates.append(
                matcher.match_candidate(candidate, pipeline.calendar_db_client)
            )
    analyzed_documents = pipeline.store.list_analyzed_documents(
        limit=limit,
        research_id=research_id,
    )
    raw_documents = pipeline.parsed_db_client.fetch_documents(
        [int(item["research_id"]) for item in analyzed_documents]
    )
    doc_by_id = {document.id: document for document in raw_documents}
    for local_document in analyzed_documents:
        parsed_document = doc_by_id.get(int(local_document["research_id"]))
        if parsed_document is None:
            continue
        extracted = raw_extractor.extract(
            document=parsed_document,
            file_id=str(local_document["file_id"])
            if local_document["file_id"] is not None
            else None,
            created_run_id=int(local_document["latest_successful_run_id"])
            if local_document["latest_successful_run_id"] is not None
            else None,
        )
        for candidate in extracted:
            candidates.append(
                matcher.match_candidate(candidate, pipeline.calendar_db_client)
            )
    stored_count = (
        0 if dry_run else pipeline.store.upsert_forecast_candidates(candidates)
    )
    return {
        "dry_run": dry_run,
        "deleted_count": deleted_count,
        "source_count": len(assertion_sources),
        "raw_document_count": len(analyzed_documents),
        "candidate_count": len(candidates),
        "would_store_count": len(candidates),
        "stored_count": stored_count,
        "sample_candidates": [asdict(candidate) for candidate in candidates[:10]],
    }


def _upload_forecasts_report(
    pipeline: RunBatchPipeline,
    *,
    limit: int | None,
) -> dict[str, object]:
    matcher = ForecastMatcher()
    candidates = pipeline.store.list_forecast_candidates(
        review_status="approved",
        upload_status="not_uploaded",
        limit=limit,
    )
    uploaded_count = 0
    skipped: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    for candidate in candidates:
        try:
            payload = matcher.to_upload_payload(candidate)
            pipeline.parsed_db_client.insert_economic_event_forecasts([payload])
            pipeline.store.mark_forecast_upload_result(
                candidate_id=candidate.id,
                upload_status="uploaded",
                review_status="uploaded",
            )
            uploaded_count += 1
        except Exception as exc:  # pragma: no cover - network exercised via CLI
            if isinstance(exc, HTTPError) and exc.code == 409:
                pipeline.store.mark_forecast_upload_result(
                    candidate_id=candidate.id,
                    upload_status="uploaded",
                    review_status="uploaded",
                    review_notes="already_uploaded_conflict",
                )
                uploaded_count += 1
                continue
            pipeline.store.mark_forecast_upload_result(
                candidate_id=candidate.id,
                upload_status="failed",
                review_notes=str(exc),
            )
            failed.append({"candidate_id": candidate.id, "error": str(exc)})
    return {
        "candidate_count": len(candidates),
        "uploaded_count": uploaded_count,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "failed_count": len(failed),
        "failures": failed,
    }


def command_review_document(
    settings: Settings,
    *,
    research_id: int,
    document_hash: str | None,
) -> int:
    pipeline = build_app(settings)
    harness = ReviewHarness(pipeline.store)
    payload = harness.review_document(
        research_id=research_id,
        document_hash=document_hash,
    )
    if payload is None:
        print(
            json.dumps(
                {"error": "document_review_not_found", "research_id": research_id},
                indent=2,
            )
        )
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_list_agents(settings: Settings) -> int:
    del settings
    registry = get_registry()
    payload = [
        {
            "name": config.name,
            "model": config.model,
            "fallback_model": config.fallback_model,
            "timeout_seconds": config.timeout_seconds,
            "retry_count": config.retry_count,
            "priority": config.priority,
            "table_name": config.table_name,
            "prompt_path": config.prompt_path,
            "tools": config.tools or [],
            "max_tool_calls": config.max_tool_calls,
            "output_schema": config.output_schema,
            "prompt_resolved": registry.resolve_prompt_path(config.name) is not None,
        }
        for config in registry.list_agents()
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_export_dispatch_batch(
    settings: Settings,
    date_from: str | None,
    date_to: str | None,
    document_keys: str | None,
    batch_key: str,
    out: str | None,
    include_orphans: bool,
) -> int:
    """Export a dispatch batch to JSON file."""
    import os
    from datetime import datetime
    from pathlib import Path

    from research_analysis_layer.models.dispatch_scope import (
        DispatchScope,
        DispatchScopeError,
    )
    from research_analysis_layer.services.dispatch_batch_exporter import (
        DispatchBatchExporter,
    )

    batch_out_dir = settings.analyst_batch_out_dir
    if out is None:
        out = str(batch_out_dir / f"dispatch-batch-{batch_key}.json")
    else:
        out = out

    try:
        scope = DispatchScope(
            date_from=datetime.fromisoformat(date_from) if date_from else None,
            date_to=datetime.fromisoformat(date_to) if date_to else None,
            document_keys=[k.strip() for k in document_keys.split(",")]
            if document_keys
            else None,
            batch_key=batch_key,
            include_orphans=include_orphans,
        )
    except DispatchScopeError as e:
        logger.error("Invalid scope: %s", e)
        return 1

    store = AnalysisStore(settings.analysis_db_path)
    exporter = DispatchBatchExporter(store)

    try:
        output_path = Path(out)
        exporter.export_to_file(scope, output_path)
        logger.info("Exported to %s", output_path)

        batch_out_dir.mkdir(parents=True, exist_ok=True)
        latest_link = batch_out_dir / "latest.json"
        if latest_link.exists() or latest_link.is_symlink():
            latest_link.unlink()
        os.symlink(output_path.name, latest_link)
        logger.info("Updated latest.json symlink to %s", output_path.name)

        return 0
    except DispatchScopeError as e:
        logger.error("Export failed: %s", e)
        return 1
    except Exception as e:
        logger.exception("Export failed")
        return 1


def _parse_candidate_ids(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _parse_agents(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap research analysis layer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "doctor", help="Check config, upstream connectivity, and local store"
    )

    run_parser = subparsers.add_parser("run", help="Run one cron-style batch")
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--skip-agents", action="store_true")
    run_parser.add_argument("--agents", type=_parse_agents, default=None)

    reprocess = subparsers.add_parser("reprocess", help="Reprocess one document")
    reprocess.add_argument("--file-id", type=str, default=None)
    reprocess.add_argument("--research-id", type=int, default=None)
    reprocess.add_argument("--document-hash", type=str, default=None)
    reprocess.add_argument("--skip-agents", action="store_true")
    reprocess.add_argument("--agents", type=_parse_agents, default=None)
    reprocess.add_argument("--agent-only", action="store_true")

    backfill = subparsers.add_parser("backfill", help="Bootstrap backfill entrypoint")
    backfill.add_argument("--date-from", type=str, default=None)
    backfill.add_argument("--date-to", type=str, default=None)
    backfill.add_argument("--source", type=str, default=None)
    backfill.add_argument("--limit", type=int, default=None)
    backfill.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Allow warning-bearing documents to be written during backfill.",
    )
    backfill.add_argument(
        "--apply",
        action="store_true",
        help="Persist analysis writes. Without this flag, backfill runs in preview mode.",
    )
    backfill.add_argument("--skip-agents", action="store_true")
    backfill.add_argument("--agents", type=_parse_agents, default=None)

    reconcile = subparsers.add_parser(
        "reconcile", help="Check recent parser-success rows against parsed DB"
    )
    reconcile.add_argument("--limit", type=int, default=50)

    extract_forecasts = subparsers.add_parser(
        "extract-forecasts",
        help="Extract local economic forecast candidates from analyzed forecast assertions",
    )
    extract_forecasts.add_argument("--limit", type=int, default=None)
    extract_forecasts.add_argument("--research-id", type=int, default=None)
    extract_forecasts.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing local forecast candidates first, then rebuild from source assertions.",
    )
    extract_forecasts.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview forecast extraction and matching without deleting or writing local candidates.",
    )

    review_forecasts = subparsers.add_parser(
        "review-forecast-candidates",
        help="Inspect locally staged forecast candidates before review or upload",
    )
    review_forecasts.add_argument("--review-status", type=str, default=None)
    review_forecasts.add_argument("--upload-status", type=str, default=None)
    review_forecasts.add_argument("--limit", type=int, default=50)

    set_forecast_review = subparsers.add_parser(
        "set-forecast-review",
        help="Set review status for one or more local forecast candidates",
    )
    set_forecast_review.add_argument(
        "--candidate-ids", type=_parse_candidate_ids, required=True
    )
    set_forecast_review.add_argument("--review-status", type=str, required=True)
    set_forecast_review.add_argument("--review-notes", type=str, default=None)

    upload_forecasts = subparsers.add_parser(
        "upload-forecasts",
        help="Upload approved forecast candidates to Supabase",
    )
    upload_forecasts.add_argument("--limit", type=int, default=25)

    sync_forecasts = subparsers.add_parser(
        "sync-forecasts",
        help="Extract local forecast candidates and upload approved matched rows",
    )
    sync_forecasts.add_argument("--extract-limit", type=int, default=None)
    sync_forecasts.add_argument("--upload-limit", type=int, default=250)

    review_document = subparsers.add_parser(
        "review-document",
        help="Build a local review payload for one analyzed document",
    )
    review_document.add_argument("--research-id", type=int, required=True)
    review_document.add_argument("--document-hash", type=str, default=None)

    subparsers.add_parser("list-agents", help="List configured analysis agents")

    export_parser = subparsers.add_parser(
        "export-dispatch-batch",
        help="Export a dispatch batch from document_analysis table",
    )
    export_parser.add_argument(
        "--date-from", type=str, default=None, help="ISO date (YYYY-MM-DD)"
    )
    export_parser.add_argument(
        "--date-to", type=str, default=None, help="ISO date (YYYY-MM-DD)"
    )
    export_parser.add_argument(
        "--document-keys", type=str, default=None, help="Comma-separated document keys"
    )
    export_parser.add_argument("--batch-key", type=str, required=True)
    export_parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output JSON file path (default: ANALYST_BATCH_OUT_DIR/dispatch-batch-<batch_key>.json)",
    )
    export_parser.add_argument(
        "--include-orphans", type=str, default="true", choices=["true", "false"]
    )

    resolve_referents = subparsers.add_parser(
        "resolve-referents",
        help="Score the referent golden set and optionally backfill referent_key on stored maps",
    )
    resolve_referents.add_argument(
        "--golden",
        type=str,
        default=None,
        help="Path to referents.jsonl (default: evals/golden/referents.jsonl)",
    )
    resolve_referents.add_argument(
        "--apply",
        action="store_true",
        help="Write resolved referent_key values back into document_analysis.payload_json",
    )
    resolve_referents.add_argument("--limit", type=int, default=None)
    resolve_referents.add_argument(
        "--granularity",
        type=str,
        default=None,
        help="Override REFERENT_GRANULARITY (coarse|fine)",
    )

    resolve_claims = subparsers.add_parser(
        "resolve-claims",
        help="Score the claim golden set and optionally backfill claim_key on stored maps",
    )
    resolve_claims.add_argument(
        "--golden",
        type=str,
        default=None,
        help="Path to claims.jsonl (default: evals/golden/claims.jsonl)",
    )
    resolve_claims.add_argument(
        "--apply",
        action="store_true",
        help="Write resolved claim_key values back into document_analysis.payload_json",
    )
    resolve_claims.add_argument("--limit", type=int, default=None)

    consensus = subparsers.add_parser(
        "consensus",
        help="Cluster stored argument maps into consensus and divergence points",
    )
    consensus.add_argument(
        "--min-publishers",
        type=int,
        default=None,
        help="Override CONSENSUS_MIN_PUBLISHERS (default 2)",
    )
    consensus.add_argument("--limit", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging(logging.INFO)
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()

    if args.command == "doctor":
        return command_doctor(settings)
    if args.command == "run":
        return command_run(
            settings,
            limit=args.limit,
            skip_agents=args.skip_agents,
            agents=args.agents,
        )
    if args.command == "reprocess":
        if not any([args.file_id, args.research_id, args.document_hash]):
            parser.error(
                "reprocess requires --file-id, --research-id, or --document-hash"
            )
        if args.agent_only and args.skip_agents:
            parser.error(
                "reprocess cannot use --agent-only together with --skip-agents"
            )
        return command_reprocess(
            settings,
            file_id=args.file_id,
            research_id=args.research_id,
            document_hash=args.document_hash,
            skip_agents=args.skip_agents,
            agents=args.agents,
            agent_only=args.agent_only,
        )
    if args.command == "backfill":
        allow_warnings = (
            args.allow_warnings or not settings.backfill_require_warning_free
        )
        return command_backfill(
            settings,
            date_from=args.date_from,
            date_to=args.date_to,
            source=args.source,
            limit=args.limit,
            apply=args.apply,
            allow_warnings=allow_warnings,
            skip_agents=args.skip_agents,
            agents=args.agents,
        )
    if args.command == "reconcile":
        return command_reconcile(settings, limit=args.limit)
    if args.command == "extract-forecasts":
        return command_extract_forecasts(
            settings,
            limit=args.limit,
            research_id=args.research_id,
            rebuild=args.rebuild,
            dry_run=args.dry_run,
        )
    if args.command == "review-forecast-candidates":
        return command_review_forecasts(
            settings,
            review_status=args.review_status,
            upload_status=args.upload_status,
            limit=args.limit,
        )
    if args.command == "set-forecast-review":
        return command_set_forecast_review(
            settings,
            candidate_ids=args.candidate_ids,
            review_status=args.review_status,
            review_notes=args.review_notes,
        )
    if args.command == "upload-forecasts":
        return command_upload_forecasts(
            settings,
            limit=args.limit,
        )
    if args.command == "sync-forecasts":
        return command_sync_forecasts(
            settings,
            extract_limit=args.extract_limit,
            upload_limit=args.upload_limit,
        )
    if args.command == "review-document":
        return command_review_document(
            settings,
            research_id=args.research_id,
            document_hash=args.document_hash,
        )
    if args.command == "list-agents":
        return command_list_agents(settings)
    if args.command == "export-dispatch-batch":
        return command_export_dispatch_batch(
            settings,
            date_from=args.date_from,
            date_to=args.date_to,
            document_keys=args.document_keys,
            batch_key=args.batch_key,
            out=args.out,
            include_orphans=args.include_orphans == "true",
        )
    if args.command == "resolve-referents":
        return command_resolve_referents(
            settings,
            golden=args.golden,
            apply=args.apply,
            limit=args.limit,
            granularity=args.granularity,
        )
    if args.command == "resolve-claims":
        return command_resolve_claims(
            settings,
            golden=args.golden,
            apply=args.apply,
            limit=args.limit,
        )
    if args.command == "consensus":
        return command_consensus(
            settings,
            min_publishers=args.min_publishers,
            limit=args.limit,
        )
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
