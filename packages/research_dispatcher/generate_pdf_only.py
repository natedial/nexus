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
    print(f"Retrieved {len(data)} records")

    print("Formatting report...")
    formatter = ReportFormatter()
    report_data = formatter.format_report(data)

    print("Generating PDF...")
    pdf_generator = PDFGenerator()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pdf_filename = f"research_report_{timestamp}.pdf"
    pdf_path = pdf_generator.generate(report_data, pdf_filename)

    print(f"✓ PDF generated: {pdf_path}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
