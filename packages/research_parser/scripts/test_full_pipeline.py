#!/usr/bin/env python3
"""Test the full pipeline end-to-end."""

from src.config import get_settings
from src.pipeline import Pipeline


def main():
    print("=" * 60)
    print("FULL PIPELINE TEST")
    print("=" * 60)

    print("\nInitializing pipeline...")
    settings = get_settings()
    pipeline = Pipeline(settings)

    print("\nRunning one processing cycle...")
    print("(This will process the first unprocessed PDF)\n")

    processed = pipeline.run_once()

    print("\n" + "=" * 60)
    print(f"RESULT: Processed {processed} file(s)")
    print("=" * 60)

    # Show state of recently processed files
    print("\nRecent processing states:")
    from src.storage.state import StateStore
    state = StateStore(settings.state_db_path)

    # Get all records
    import sqlite3
    with sqlite3.connect(settings.state_db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT file_name, status, parse_ok, metadata_ok, themes_ok, trades_ok, synthesis_ok, storage_ok "
            "FROM processed_files ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()

        for row in rows:
            print(f"\n  {row['file_name'][:60]}...")
            print(f"    Status: {row['status']}")
            print(f"    Steps: parse={row['parse_ok']} meta={row['metadata_ok']} "
                  f"themes={row['themes_ok']} trades={row['trades_ok']} "
                  f"synth={row['synthesis_ok']} storage={row['storage_ok']}")


if __name__ == "__main__":
    main()
