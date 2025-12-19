#!/usr/bin/env python3
"""Quick test to verify database connection and query."""

from config import Config
from src.database import DatabaseClient
import json

try:
    # Validate config
    print("Validating configuration...")
    Config.validate()
    print("✓ Configuration valid\n")

    # Test connection
    print("Connecting to Supabase...")
    db = DatabaseClient()
    print("✓ Connected\n")

    # Run query
    print("Querying parsed_research (last 7 days)...")
    results = db.query_analysis()
    print(f"✓ Query successful! Found {len(results)} records\n")

    # Show sample data
    if results:
        print("Sample record structure:")
        print(json.dumps(results[0], indent=2, default=str))
    else:
        print("No records found in the last 7 days.")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
