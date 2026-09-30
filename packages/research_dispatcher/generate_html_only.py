#!/usr/bin/env python3
"""Generate print HTML report without sending email."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from src.database import DatabaseClient
from src.delta_engine import SynthesisDeltaTracker
from src.dispatch_loader import load_dispatch_documents
from src.dispatch_store import DispatchStore
from src.formatter import ReportFormatter
from src.html_generator import HtmlReportGenerator
from src.main import _derive_dispatch_batch_key
from src.synthesizer import Synthesizer


try:
    print("Validating configuration...")
    Config.validate()
    dispatch_store = DispatchStore(Config.DISPATCH_DB_PATH)
    dispatch_run_id = None

    db = DatabaseClient()
    dispatch_batch = None
    source_type = "analyst_batch"
    print(f"Loading analyst dispatch batch: {Config.ANALYST_BATCH_PATH}")
    data, dispatch_batch, source_type = load_dispatch_documents(
        analyst_batch_path=Config.ANALYST_BATCH_PATH,
    )
    print(
        f"Loaded batch {dispatch_batch.batch_key} with "
        f"{len(dispatch_batch.documents)} document(s)"
    )

    economic_events = db.query_economic_events()
    print(f"Retrieved {len(economic_events)} economic events")

    supply_events = db.query_supply_events()
    print(f"Retrieved {len(supply_events)} supply events")

    if not data:
        print("No documents to process.")
        sys.exit(0)

    synthesis_result = None
    synthesis_snapshot = None
    active_filters = {}
    if Config.FILTER_REGION:
        active_filters["region"] = Config.FILTER_REGION
    if Config.FILTER_ASSET_FOCUS:
        active_filters["asset_focus"] = Config.FILTER_ASSET_FOCUS
    if Config.FILTER_SOURCES:
        active_filters["sources"] = Config.FILTER_SOURCES
    if Config.DATE_RANGE_DAYS != 7:
        active_filters["date_range_days"] = Config.DATE_RANGE_DAYS

    if Config.ENABLE_SYNTHESIS and (
        Config.ANTHROPIC_API_KEY
        or Config.OPENAI_API_KEY
        or Config.DEEPINFRA_API_KEY
        or Config.OPENROUTER_API_KEY
    ):
        print("Running cross-document synthesis...")
        if Config.USE_SKILL_PIPELINE:
            print("Using skill-based pipeline")
        synthesizer = Synthesizer(
            anthropic_api_key=Config.ANTHROPIC_API_KEY,
            openai_api_key=Config.OPENAI_API_KEY,
            deepinfra_api_key=Config.DEEPINFRA_API_KEY,
            openrouter_api_key=Config.OPENROUTER_API_KEY,
            use_skill_pipeline=Config.USE_SKILL_PIPELINE,
        )
        synthesis_input = dispatch_batch if dispatch_batch is not None else data
        synthesis_result = synthesizer.synthesize(synthesis_input, scope=active_filters)
        if synthesis_result:
            print(f"✓ Synthesis complete: {synthesis_result.title}")
        else:
            print("⚠ Synthesis failed or returned no results")
    elif not Config.ENABLE_SYNTHESIS:
        print("Synthesis disabled (ENABLE_SYNTHESIS=false)")
    else:
        print(
            "Synthesis skipped (no ANTHROPIC_API_KEY, OPENAI_API_KEY, "
            "DEEPINFRA_API_KEY, or OPENROUTER_API_KEY)"
        )

    print("Formatting report...")
    formatter = ReportFormatter()

    if Config.FILTER_TRADE_CONVICTION != "all":
        active_filters["trade_conviction"] = Config.FILTER_TRADE_CONVICTION
    report_source = dispatch_batch if dispatch_batch is not None else data
    report_data = formatter.format_report(
        report_source,
        active_filters=active_filters,
        conviction_filter=Config.FILTER_TRADE_CONVICTION,
        input_mode=Config.DISPATCH_INPUT_MODE,
        source_pipeline=(
            "research_analyst"
            if Config.DISPATCH_INPUT_MODE == "analyst"
            else "parsed_research"
        ),
        analyst_batch_path=(
            Config.ANALYST_BATCH_PATH
            if Config.DISPATCH_INPUT_MODE == "analyst"
            else None
        ),
    )
    batch_key = _derive_dispatch_batch_key(
        dispatch_batch=dispatch_batch,
        active_filters=active_filters,
        source_date_range=report_data.get("source_date_range"),
    )
    dispatch_run_id = dispatch_store.create_run(
        run_type="html_only",
        mode=Config.MODE,
        batch_key=batch_key,
        analysis_version=(
            dispatch_batch.analysis_version if dispatch_batch is not None else None
        ),
        report_title=report_data.get("title", Config.REPORT_TITLE),
        report_scope=active_filters,
        source_date_range=report_data.get("source_date_range"),
        document_count=len(data),
        input_mode=Config.DISPATCH_INPUT_MODE,
        source_type=source_type,
        analyst_batch_path=(
            Config.ANALYST_BATCH_PATH
            if Config.DISPATCH_INPUT_MODE == "analyst"
            else None
        ),
    )
    dispatch_store.record_documents(
        dispatch_run_id,
        dispatch_batch if dispatch_batch is not None else data,
    )

    if synthesis_result:
        delta_tracker = SynthesisDeltaTracker()
        synthesis_snapshot, synthesis_delta = delta_tracker.prepare_report(
            synthesis_result,
            report_data,
        )
        report_data["synthesis"] = synthesis_result.to_dict()
        report_data["synthesis_delta"] = synthesis_delta
        report_data["through_lines"] = synthesis_result.through_lines
        report_data["callouts"] = synthesis_result.callouts
        report_data["analysis_paragraphs"] = synthesis_result.analysis_paragraphs
        report_data["executive_summary"] = synthesis_result.executive_summary
        report_data["themes_by_through_line"] = formatter.group_themes_by_through_lines(
            report_data.get("themes_analysis", []),
            synthesis_result.through_lines,
        )

    report_data["economic_calendar"] = formatter.format_economic_calendar(economic_events)
    report_data["supply_calendar"] = formatter.format_supply_calendar(supply_events)

    print("Generating print HTML...")
    html_generator = HtmlReportGenerator()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_filename = f"research_report_{timestamp}.html"
    html_path = html_generator.generate(report_data, html_filename)
    dispatch_store.mark_pdf_generated(
        dispatch_run_id,
        pdf_path=html_path,
        throughline_count=len(report_data.get("through_lines", [])),
        callout_count=len(report_data.get("callouts", [])),
    )
    if synthesis_snapshot is not None:
        SynthesisDeltaTracker().save_snapshot(synthesis_snapshot)
        dispatch_store.save_snapshot(
            dispatch_run_id,
            snapshot_type="synthesis_snapshot",
            payload=synthesis_snapshot,
        )
    dispatch_store.finalize_run(dispatch_run_id, status="completed")

    print(f"✓ HTML generated: {html_path}")

except Exception as e:
    if "dispatch_run_id" in locals() and dispatch_run_id is not None:
        dispatch_store.finalize_run(
            dispatch_run_id,
            status="failed",
            error_text=str(e),
        )
    print(f"✗ Error: {e}")
    import traceback

    traceback.print_exc()
