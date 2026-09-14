#!/usr/bin/env python3
"""
Research Dispatch - Automated Document Analysis Reporting

This script queries a Supabase database, formats the results,
generates a PDF report, and emails it.
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from config import Config
from research_pipeline_ops import PipelineOpsClient
from src.analyst_client import AnalystBatchClient
from src.database import DatabaseClient
from src.dispatch_store import DispatchStore
from src.delta_engine import SynthesisDeltaTracker
from src.formatter import ReportFormatter
from src.pdf_generator import PDFGenerator
from src.email_sender import EmailSender
from src.synthesizer import Synthesizer

logger = logging.getLogger(__name__)


def _derive_dispatch_batch_key(
    *,
    dispatch_batch,
    active_filters: dict[str, object],
    source_date_range: dict[str, str] | None,
) -> str:
    """Build a stable batch key for local dispatch tracking."""
    if dispatch_batch is not None:
        return dispatch_batch.batch_key

    start = (source_date_range or {}).get("start", "na")
    end = (source_date_range or {}).get("end", "na")
    region = active_filters.get("region") or "all"
    asset_focus = active_filters.get("asset_focus") or "all"
    sources = str(active_filters.get("sources") or "all").replace(" ", "")
    return f"legacy:{start}:{end}:{region}:{asset_focus}:{sources}"


def _load_dispatch_documents(
    *,
    input_mode: str,
    analyst_batch_path: str,
    db_client: DatabaseClient,
) -> tuple[list[dict], object | None, str]:
    """Load dispatcher input from the explicitly selected source."""
    if input_mode == "parser":
        data = db_client.query_analysis()
        return data, None, "parsed_research"
    if input_mode == "analyst":
        dispatch_batch = AnalystBatchClient(analyst_batch_path).load_batch()
        return dispatch_batch.to_legacy_records(), dispatch_batch, "analyst_batch"
    raise ValueError("DISPATCH_INPUT_MODE must be one of: parser, analyst")


def main():
    """Main execution flow."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting Research Dispatch")
    logger.info("Mode: %s", Config.MODE)
    logger.info("Input mode: %s", Config.DISPATCH_INPUT_MODE)
    dispatch_store = DispatchStore(Config.DISPATCH_DB_PATH)
    ops = PipelineOpsClient.from_env(
        default_spool_db_path=str(
            Path(Config.DISPATCH_DB_PATH).parent / "pipeline_ops_spool.db"
        ),
        emitted_by="research_dispatcher",
    )
    ops.flush()
    dispatch_run_id: int | None = None
    ops_run_key = ops.start_run(
        repo_name="research_dispatcher",
        stage_family="dispatcher",
        run_type="email_dispatch",
        trigger_source="manual_or_scheduler",
        stats={
            "mode": Config.MODE,
            "input_mode": Config.DISPATCH_INPUT_MODE,
            "analyst_batch_path": (
                Config.ANALYST_BATCH_PATH
                if Config.DISPATCH_INPUT_MODE == "analyst"
                else None
            ),
        },
    )

    try:
        # Validate configuration
        logger.info("Validating configuration...")
        Config.validate()

        # Query database
        logger.info("Connecting to data sources...")
        db_client = DatabaseClient()
        dispatch_batch = None
        source_type = (
            "analyst_batch"
            if Config.DISPATCH_INPUT_MODE == "analyst"
            else "parsed_research"
        )

        with ops.track_stage(
            repo_name="research_dispatcher",
            stage_name="dispatcher.select_documents",
            run_key=ops_run_key,
            payload={
                "input_mode": Config.DISPATCH_INPUT_MODE,
                "source_type": source_type,
                "analyst_batch_path": (
                    Config.ANALYST_BATCH_PATH
                    if Config.DISPATCH_INPUT_MODE == "analyst"
                    else None
                ),
            },
        ):
            if Config.DISPATCH_INPUT_MODE == "analyst":
                logger.info(
                    "Loading analyst dispatch batch: %s", Config.ANALYST_BATCH_PATH
                )
            else:
                logger.info("Querying parsed_research documents")
            data, dispatch_batch, source_type = _load_dispatch_documents(
                input_mode=Config.DISPATCH_INPUT_MODE,
                analyst_batch_path=Config.ANALYST_BATCH_PATH,
                db_client=db_client,
            )
            if dispatch_batch is not None:
                logger.info(
                    "Loaded batch %s with %d document(s)",
                    dispatch_batch.batch_key,
                    len(dispatch_batch.documents),
                )
            else:
                logger.info("Retrieved %d research records", len(data))

        # Query calendar data
        with ops.track_stage(
            repo_name="research_dispatcher",
            stage_name="dispatcher.query_calendar",
            run_key=ops_run_key,
        ):
            economic_events = db_client.query_economic_events()
            logger.info("Retrieved %d economic events", len(economic_events))

            supply_events = db_client.query_supply_events()
            logger.info("Retrieved %d supply events", len(supply_events))

        if not data:
            logger.info("No documents to process.")
            ops.update_run(
                ops_run_key,
                status="completed",
                stats={
                    "document_count": 0,
                    "input_mode": Config.DISPATCH_INPUT_MODE,
                    "source_type": source_type,
                    "economic_events": len(economic_events),
                    "supply_events": len(supply_events),
                },
                completed=True,
            )
            return 0

        # Extract document IDs for later update
        document_ids = [record["id"] for record in data]

        # Build active filters for display in report and synthesis scope
        active_filters = {}
        if Config.FILTER_REGION:
            active_filters["region"] = Config.FILTER_REGION
        if Config.FILTER_ASSET_FOCUS:
            active_filters["asset_focus"] = Config.FILTER_ASSET_FOCUS
        if Config.FILTER_SOURCES:
            active_filters["sources"] = Config.FILTER_SOURCES
        if Config.DATE_RANGE_DAYS != 7:  # Only show if not default
            active_filters["date_range_days"] = Config.DATE_RANGE_DAYS

        # Run cross-document synthesis
        synthesis_result = None
        synthesis_snapshot = None
        if Config.ENABLE_SYNTHESIS and (
            Config.ANTHROPIC_API_KEY
            or Config.OPENAI_API_KEY
            or Config.DEEPINFRA_API_KEY
            or Config.OPENROUTER_API_KEY
        ):
            with ops.track_stage(
                repo_name="research_dispatcher",
                stage_name="dispatcher.synthesize_batch",
                run_key=ops_run_key,
                payload={
                    "document_count": len(data),
                    "input_mode": Config.DISPATCH_INPUT_MODE,
                    "source_type": source_type,
                    "use_skill_pipeline": Config.USE_SKILL_PIPELINE,
                },
            ):
                logger.info("Running cross-document synthesis...")
                if Config.USE_SKILL_PIPELINE:
                    logger.info("Using skill-based pipeline")
                synthesizer = Synthesizer(
                    anthropic_api_key=Config.ANTHROPIC_API_KEY,
                    openai_api_key=Config.OPENAI_API_KEY,
                    deepinfra_api_key=Config.DEEPINFRA_API_KEY,
                    openrouter_api_key=Config.OPENROUTER_API_KEY,
                    use_skill_pipeline=Config.USE_SKILL_PIPELINE,
                )
                synthesis_input = dispatch_batch if dispatch_batch is not None else data
                synthesis_result = synthesizer.synthesize(
                    synthesis_input, scope=active_filters
                )
                if synthesis_result:
                    logger.info("Synthesis complete: %s", synthesis_result.title)
                else:
                    logger.warning("Synthesis failed or returned no results")
        elif not Config.ENABLE_SYNTHESIS:
            logger.info("Synthesis disabled (ENABLE_SYNTHESIS=false)")
        else:
            logger.warning(
                "Synthesis skipped (no ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPINFRA_API_KEY, or OPENROUTER_API_KEY)"
            )

        # Format data
        logger.info("Formatting report...")
        formatter = ReportFormatter()

        with ops.track_stage(
            repo_name="research_dispatcher",
            stage_name="dispatcher.format_report",
            run_key=ops_run_key,
            payload={"document_count": len(data)},
        ):
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
            run_type="email_dispatch",
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

        # Add cross-document synthesis to report (replaces per-document through_lines)
        if synthesis_result:
            delta_tracker = SynthesisDeltaTracker()
            synthesis_snapshot, synthesis_delta = delta_tracker.prepare_report(
                synthesis_result,
                report_data,
            )
            report_data["synthesis"] = synthesis_result.to_dict()
            report_data["synthesis_delta"] = synthesis_delta
            report_data["through_lines"] = (
                synthesis_result.through_lines
            )  # Override aggregated
            report_data["callouts"] = synthesis_result.callouts  # Override aggregated
            report_data["analysis_paragraphs"] = synthesis_result.analysis_paragraphs
            report_data["executive_summary"] = synthesis_result.executive_summary
            report_data["themes_by_through_line"] = (
                formatter.group_themes_by_through_lines(
                    report_data.get("themes_analysis", []),
                    synthesis_result.through_lines,
                )
            )

        # Add calendar data to report
        report_data["economic_calendar"] = formatter.format_economic_calendar(
            economic_events
        )
        report_data["supply_calendar"] = formatter.format_supply_calendar(supply_events)

        # Generate PDF
        logger.info("Generating PDF...")
        with ops.track_stage(
            repo_name="research_dispatcher",
            stage_name="dispatcher.generate_pdf",
            run_key=ops_run_key,
            payload={"document_count": len(data)},
        ):
            pdf_generator = PDFGenerator(format_rules_path="format_rules.yaml")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pdf_filename = f"research_report_{timestamp}.pdf"
            pdf_path = pdf_generator.generate(report_data, pdf_filename)
        logger.info("PDF generated: %s", pdf_path)
        dispatch_store.mark_pdf_generated(
            dispatch_run_id,
            pdf_path=pdf_path,
            throughline_count=len(report_data.get("through_lines", [])),
            callout_count=len(report_data.get("callouts", [])),
        )

        # Send email
        logger.info("Sending email...")
        with ops.track_stage(
            repo_name="research_dispatcher",
            stage_name="dispatcher.send_email",
            run_key=ops_run_key,
            payload={"pdf_path": pdf_path},
        ):
            email_sender = EmailSender()
            recipient_list = email_sender.send_report(pdf_path)
        logger.info(
            "Email sent to %d recipient(s): %s",
            len(recipient_list),
            ", ".join(recipient_list),
        )
        dispatch_store.mark_sent(dispatch_run_id, recipient_list)

        if synthesis_snapshot is not None:
            SynthesisDeltaTracker().save_snapshot(synthesis_snapshot)
            dispatch_store.save_snapshot(
                dispatch_run_id,
                snapshot_type="synthesis_snapshot",
                payload=synthesis_snapshot,
            )
            logger.info("Saved synthesis snapshot for delta tracking")

        # Legacy compatibility path: optionally mirror dispatch completion into parser-owned state
        if Config.DISPATCH_INPUT_MODE == "analyst":
            logger.info("Analyst batch mode: skipping parser synthesized flag update")
        elif not Config.LEGACY_SYNTHESIZED_UPDATES:
            logger.info(
                "Legacy parser synthesized updates disabled; dispatch ledger is the source of truth"
            )
        elif Config.MODE in ["production", "prod", "active"]:
            logger.info(
                "Legacy fallback enabled: marking %d document(s) synthesized in parser state",
                len(document_ids),
            )
            if db_client.mark_as_synthesized(document_ids):
                logger.info("Documents marked as synthesized")
            else:
                logger.warning("Failed to mark documents as synthesized")
        else:
            logger.info("Debug mode: Skipping legacy synthesized flag update")

        ops.emit_stage_event(
            repo_name="research_dispatcher",
            stage_name="dispatcher.complete",
            status="succeeded",
            run_key=ops_run_key,
            payload={
                "document_count": len(data),
                "throughline_count": len(report_data.get("through_lines", [])),
                "callout_count": len(report_data.get("callouts", [])),
                "recipient_count": len(recipient_list),
                "batch_key": batch_key,
                "input_mode": Config.DISPATCH_INPUT_MODE,
                "source_type": source_type,
            },
        )
        ops.update_run(
            ops_run_key,
            status="completed",
            stats={
                "document_count": len(data),
                "economic_events": len(economic_events),
                "supply_events": len(supply_events),
                "throughline_count": len(report_data.get("through_lines", [])),
                "callout_count": len(report_data.get("callouts", [])),
                "recipient_count": len(recipient_list),
                "batch_key": batch_key,
                "input_mode": Config.DISPATCH_INPUT_MODE,
                "source_type": source_type,
            },
            completed=True,
        )
        dispatch_store.finalize_run(dispatch_run_id, status="completed")
        logger.info("Research Dispatch completed successfully")
        ops.flush()
        return 0

    except Exception as e:
        ops.emit_stage_event(
            repo_name="research_dispatcher",
            stage_name="dispatcher.complete",
            status="failed",
            run_key=ops_run_key,
            payload={"dispatch_run_id": dispatch_run_id},
            error_type=e.__class__.__name__,
            error_text=str(e),
        )
        ops.update_run(
            ops_run_key,
            status="failed",
            error_text=str(e),
            stats={"dispatch_run_id": dispatch_run_id},
            completed=True,
        )
        if dispatch_run_id is not None:
            dispatch_store.finalize_run(
                dispatch_run_id,
                status="failed",
                error_text=str(e),
            )
        logger.exception("Unhandled error: %s", str(e))
        ops.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
