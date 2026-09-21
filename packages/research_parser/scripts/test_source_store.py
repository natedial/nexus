#!/usr/bin/env python3
"""Test PostgreSQL source store connection."""

from src.config import get_settings
from src.storage import PostgresSourceStore


def main():
    print("Loading settings...")
    settings = get_settings()
    print(f"  Database URL: {settings.database_url[:48]}...")

    print("\nConnecting to PostgreSQL...")
    store = PostgresSourceStore(database_url=settings.database_url)

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM parsed_research").fetchone()
        count = row["count"] if row else 0
        print(f"  Connection successful (parsed_research rows: {count})")

    print("\n--- PostgreSQL source store verified! ---")


if __name__ == "__main__":
    main()
