#!/usr/bin/env python3
"""Test Supabase connection and the full pipeline."""

from src.config import get_settings
from src.storage import SupabaseClient


def main():
    print("Loading settings...")
    settings = get_settings()
    print(f"  Supabase URL: {settings.supabase_url[:50]}...")

    print("\nConnecting to Supabase...")
    client = SupabaseClient(
        url=settings.supabase_url,
        key=settings.supabase_key,
    )

    # Test connection by querying the table
    print("\nTesting connection (querying parsed_research table)...")
    try:
        response = client._client.table("parsed_research").select("*").limit(1).execute()
        print(f"  Connection successful!")
        print(f"  Existing records: {len(response.data)}")
        if response.data:
            print(f"  Sample record keys: {list(response.data[0].keys())}")
    except Exception as e:
        print(f"  Error: {e}")
        print("\n  If the table doesn't exist, create it with this SQL in Supabase:")
        print("""
  CREATE TABLE parsed_research (
      id SERIAL PRIMARY KEY,
      parsed_data JSONB NOT NULL,
      source_date DATE,
      source TEXT,
      document_name TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
        """)
        return

    print("\n--- Supabase connection verified! ---")


if __name__ == "__main__":
    main()
