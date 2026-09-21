#!/usr/bin/env python3
"""Quick test to verify PostgreSQL calendar queries."""

from config import Config
from src.database import DatabaseClient
import json

try:
    print("Validating configuration...")
    Config.validate()
    print("Configuration valid\n")

    print("Connecting to PostgreSQL calendar tables...")
    db = DatabaseClient()
    print("Connected\n")

    print("Querying economic_events for the upcoming week...")
    economic_events = db.query_economic_events()
    print(f"Query successful! Found {len(economic_events)} economic events\n")

    print("Querying supply_events for the upcoming week...")
    supply_events = db.query_supply_events()
    print(f"Query successful! Found {len(supply_events)} supply events\n")

    if economic_events:
        print("Sample economic event:")
        print(json.dumps(economic_events[0], indent=2, default=str))

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
