#!/usr/bin/env python3
"""
Research Dispatch - Automated Document Analysis Reporting

This script queries a Supabase database, formats the results,
generates a PDF report, and emails it.
"""

import sys
import os
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from src.database import DatabaseClient
from src.formatter import ReportFormatter
from src.pdf_generator import PDFGenerator
from src.email_sender import EmailSender


def main():
    """Main execution flow."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Research Dispatch...")
    print(f"Mode: {Config.MODE}")

    try:
        # Validate configuration
        print("Validating configuration...")
        Config.validate()

        # Query database
        print("Connecting to database...")
        db_client = DatabaseClient()
        print("Querying documents...")
        data = db_client.query_analysis()
        print(f"Retrieved {len(data)} research records")

        # Query calendar data
        economic_events = db_client.query_economic_events()
        print(f"Retrieved {len(economic_events)} economic events")

        supply_events = db_client.query_supply_events()
        print(f"Retrieved {len(supply_events)} supply events")

        if not data:
            print("No documents to process.")
            return 0

        # Extract document IDs for later update
        document_ids = [record['id'] for record in data]

        # Format data
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

        # Generate PDF
        print("Generating PDF...")
        pdf_generator = PDFGenerator(format_rules_path='format_rules.yaml')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_filename = f"research_report_{timestamp}.pdf"
        pdf_path = pdf_generator.generate(report_data, pdf_filename)
        print(f"PDF generated: {pdf_path}")

        # Send email
        print("Sending email...")
        email_sender = EmailSender()
        recipient_list = email_sender.send_report(pdf_path)
        print(f"Email sent to {len(recipient_list)} recipient(s): {', '.join(recipient_list)}")

        # Mark documents as synthesized if in production mode
        if Config.MODE in ['production', 'prod', 'active']:
            print(f"Marking {len(document_ids)} documents as synthesized...")
            if db_client.mark_as_synthesized(document_ids):
                print("✓ Documents marked as synthesized")
            else:
                print("⚠ Warning: Failed to mark documents as synthesized")
        else:
            print(f"Debug mode: Skipping synthesized flag update")

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Research Dispatch completed successfully!")
        return 0

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
