#!/usr/bin/env python3
"""Test LlamaIndex PDF parsing with a file from Google Drive."""

from src.config import get_settings
from src.drive import DriveWatcher
from src.parser import LlamaIndexParser


def main():
    print("Loading settings...")
    settings = get_settings()

    # Get a PDF from Drive
    print("\nConnecting to Google Drive...")
    watcher = DriveWatcher(
        credentials_path=settings.google_credentials_path,
        folder_id=settings.google_drive_folder_id,
    )

    pdfs = watcher.list_pdfs()
    if not pdfs:
        print("No PDFs found in folder!")
        return

    # Pick a smaller/recent one for testing
    test_pdf = pdfs[0]
    print(f"\nTest file: {test_pdf.name}")
    print(f"  ID: {test_pdf.id}")

    # Download it
    print("\nDownloading...")
    file_path = watcher.download_file(test_pdf.id, test_pdf.name)
    print(f"  Saved to: {file_path}")
    print(f"  Size: {file_path.stat().st_size / 1024:.1f} KB")

    # Parse with LlamaIndex
    print("\nInitializing LlamaIndex parser...")
    parser = LlamaIndexParser(api_key=settings.llamaindex_api_key)

    print("\nUploading to LlamaIndex Cloud...")
    print("(This may take a minute or two...)")
    result = parser.parse(file_path)

    print(f"\nResult:")
    print(f"  Job ID: {result.job_id}")
    print(f"  Status: {result.status.value}")

    if result.markdown:
        print(f"  Markdown length: {len(result.markdown)} chars")
        print(f"\n--- First 1000 chars of markdown ---\n")
        print(result.markdown[:1000])
        print("\n--- (truncated) ---")
    elif result.error:
        print(f"  Error: {result.error}")

    # Cleanup
    file_path.unlink()
    print(f"\nCleaned up temp file.")


if __name__ == "__main__":
    main()
