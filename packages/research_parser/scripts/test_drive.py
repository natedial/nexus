#!/usr/bin/env python3
"""Test Google Drive connection and list PDFs in the watched folder."""

from src.config import get_settings
from src.drive import DriveWatcher


def main():
    print("Loading settings...")
    settings = get_settings()
    print(f"  Credentials: {settings.google_credentials_path}")
    print(f"  Folder ID: {settings.google_drive_folder_id}")

    print("\nConnecting to Google Drive...")
    watcher = DriveWatcher(
        credentials_path=settings.google_credentials_path,
        folder_id=settings.google_drive_folder_id,
    )

    print("\nListing PDFs in folder...")
    pdfs = watcher.list_pdfs()

    if not pdfs:
        print("  No PDFs found in folder.")
    else:
        print(f"  Found {len(pdfs)} PDF(s):\n")
        for pdf in pdfs:
            print(f"    - {pdf.name}")
            print(f"      ID: {pdf.id}")
            print()


if __name__ == "__main__":
    main()
