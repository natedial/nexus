#!/usr/bin/env python3
"""Test the full pipeline end-to-end."""

from src.config import get_settings
from src.pipeline import Pipeline


def main():
    print("=" * 60)
    print("FULL PIPELINE TEST (max 3 PDFs)")
    print("=" * 60)

    print("\nInitializing pipeline...")
    settings = get_settings()
    pipeline = Pipeline(settings)

    print("\nFinding new PDFs to process...")
    all_files = pipeline.drive.list_pdfs()
    new_files = [f for f in all_files if not pipeline.state.is_processed(f.id)]

    # Limit to 3 PDFs
    files_to_process = new_files[:3]

    if not files_to_process:
        print("No new files to process.")
        return

    print(f"Found {len(new_files)} new file(s), processing {len(files_to_process)}:\n")
    for f in files_to_process:
        print(f"  - {f.name}")

    print("\nProcessing files...\n")
    processed = 0
    for file in files_to_process:
        try:
            success = pipeline.process_file(file.id, file.name)
            if success:
                processed += 1
        except Exception as e:
            print(f"Error processing {file.name}: {e}")

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
            "SELECT file_name, status, parse_ok, metadata_ok, themes_ok, trades_ok, storage_ok "
            "FROM processed_files ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()

        for row in rows:
            print(f"\n  {row['file_name'][:60]}...")
            print(f"    Status: {row['status']}")
            print(f"    Steps: parse={row['parse_ok']} meta={row['metadata_ok']} "
                  f"themes={row['themes_ok']} trades={row['trades_ok']} "
                  f"storage={row['storage_ok']}")


if __name__ == "__main__":
    main()
