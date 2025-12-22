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
