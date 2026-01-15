#!/usr/bin/env python3
"""Generate PDF report without sending email."""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from src.database import DatabaseClient
from src.formatter import ReportFormatter
from src.pdf_generator import PDFGenerator
from src.synthesizer import Synthesizer

try:
    print("Validating configuration...")
    Config.validate()

    print("Querying database...")
    db = DatabaseClient()
    data = db.query_analysis()
    print(f"Retrieved {len(data)} research records")

    # Query calendar data
    economic_events = db.query_economic_events()
    print(f"Retrieved {len(economic_events)} economic events")

    supply_events = db.query_supply_events()
    print(f"Retrieved {len(supply_events)} supply events")

    if not data:
        print("No documents to process.")
        sys.exit(0)

    # Run cross-document synthesis
    synthesis_result = None
    if Config.ENABLE_SYNTHESIS and Config.ANTHROPIC_API_KEY:
        print("Running cross-document synthesis...")
        synthesizer = Synthesizer(
            anthropic_api_key=Config.ANTHROPIC_API_KEY,
            openai_api_key=Config.OPENAI_API_KEY,
        )
        synthesis_result = synthesizer.synthesize(data)
        if synthesis_result:
            print(f"✓ Synthesis complete: {synthesis_result.title}")
        else:
            print("⚠ Synthesis failed or returned no results")
    elif not Config.ENABLE_SYNTHESIS:
        print("Synthesis disabled (ENABLE_SYNTHESIS=false)")
    else:
        print("Synthesis skipped (no ANTHROPIC_API_KEY)")

    print("Formatting report...")
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
        report_data['through_lines'] = synthesis_result.through_lines
        report_data['callouts'] = synthesis_result.callouts
        report_data['themes_by_through_line'] = formatter.group_themes_by_through_lines(
            report_data.get('themes_analysis', []),
            synthesis_result.through_lines,
        )

    # Add calendar data to report
    report_data['economic_calendar'] = formatter.format_economic_calendar(economic_events)
    report_data['supply_calendar'] = formatter.format_supply_calendar(supply_events)

    print("Generating PDF...")
    # Pass the format_rules.yaml path relative to script location
    pdf_generator = PDFGenerator(format_rules_path='format_rules.yaml')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_filename = f"research_report_{timestamp}.pdf"
    pdf_path = pdf_generator.generate(report_data, pdf_filename)

    print(f"✓ PDF generated: {pdf_path}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
