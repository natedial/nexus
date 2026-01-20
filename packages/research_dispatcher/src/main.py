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

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from src.database import DatabaseClient
from src.formatter import ReportFormatter
from src.pdf_generator import PDFGenerator
from src.email_sender import EmailSender
from src.synthesizer import Synthesizer

logger = logging.getLogger(__name__)


def main():
    """Main execution flow."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting Research Dispatch")
    logger.info("Mode: %s", Config.MODE)

    try:
        # Validate configuration
        logger.info("Validating configuration...")
        Config.validate()

        # Query database
        logger.info("Connecting to database...")
        db_client = DatabaseClient()
        logger.info("Querying documents...")
        data = db_client.query_analysis()
        logger.info("Retrieved %d research records", len(data))

        # Query calendar data
        economic_events = db_client.query_economic_events()
        logger.info("Retrieved %d economic events", len(economic_events))

        supply_events = db_client.query_supply_events()
        logger.info("Retrieved %d supply events", len(supply_events))

        if not data:
            logger.info("No documents to process.")
            return 0

        # Extract document IDs for later update
        document_ids = [record['id'] for record in data]

        # Run cross-document synthesis
        synthesis_result = None
        if Config.ENABLE_SYNTHESIS and (Config.ANTHROPIC_API_KEY or Config.OPENAI_API_KEY):
            logger.info("Running cross-document synthesis...")
            if Config.USE_SKILL_PIPELINE:
                logger.info("Using skill-based pipeline")
            synthesizer = Synthesizer(
                anthropic_api_key=Config.ANTHROPIC_API_KEY,
                openai_api_key=Config.OPENAI_API_KEY,
                use_skill_pipeline=Config.USE_SKILL_PIPELINE,
            )
            synthesis_result = synthesizer.synthesize(data)
            if synthesis_result:
                logger.info("Synthesis complete: %s", synthesis_result.title)
            else:
                logger.warning("Synthesis failed or returned no results")
        elif not Config.ENABLE_SYNTHESIS:
            logger.info("Synthesis disabled (ENABLE_SYNTHESIS=false)")
        else:
            logger.warning("Synthesis skipped (no ANTHROPIC_API_KEY or OPENAI_API_KEY)")

        # Format data
        logger.info("Formatting report...")
        formatter = ReportFormatter()

        # Build active filters for display in report
        active_filters = {}
        if Config.FILTER_REGION:
            active_filters['region'] = Config.FILTER_REGION
        if Config.FILTER_ASSET_FOCUS:
            active_filters['asset_focus'] = Config.FILTER_ASSET_FOCUS
        if Config.FILTER_SOURCES:
            active_filters['sources'] = Config.FILTER_SOURCES
        if Config.DATE_RANGE_DAYS != 7:  # Only show if not default
            active_filters['date_range_days'] = Config.DATE_RANGE_DAYS

        report_data = formatter.format_report(data, active_filters=active_filters)

        # Add cross-document synthesis to report (replaces per-document through_lines)
        if synthesis_result:
            report_data['synthesis'] = synthesis_result.to_dict()
            report_data['through_lines'] = synthesis_result.through_lines  # Override aggregated
            report_data['callouts'] = synthesis_result.callouts  # Override aggregated
            report_data['themes_by_through_line'] = formatter.group_themes_by_through_lines(
                report_data.get('themes_analysis', []),
                synthesis_result.through_lines,
            )

        # Add calendar data to report
        report_data['economic_calendar'] = formatter.format_economic_calendar(economic_events)
        report_data['supply_calendar'] = formatter.format_supply_calendar(supply_events)

        # Generate PDF
        logger.info("Generating PDF...")
        pdf_generator = PDFGenerator(format_rules_path='format_rules.yaml')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_filename = f"research_report_{timestamp}.pdf"
        pdf_path = pdf_generator.generate(report_data, pdf_filename)
        logger.info("PDF generated: %s", pdf_path)

        # Send email
        logger.info("Sending email...")
        email_sender = EmailSender()
        recipient_list = email_sender.send_report(pdf_path)
        logger.info(
            "Email sent to %d recipient(s): %s",
            len(recipient_list),
            ", ".join(recipient_list),
        )

        # Mark documents as synthesized if in production mode
        if Config.MODE in ['production', 'prod', 'active']:
            logger.info("Marking %d documents as synthesized...", len(document_ids))
            if db_client.mark_as_synthesized(document_ids):
                logger.info("Documents marked as synthesized")
            else:
                logger.warning("Failed to mark documents as synthesized")
        else:
            logger.info("Debug mode: Skipping synthesized flag update")

        logger.info("Research Dispatch completed successfully")
        return 0

    except Exception as e:
        logger.exception("Unhandled error: %s", str(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
