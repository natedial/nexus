#!/usr/bin/env python3
"""Test Google Drive connection and list PDFs in the watched folder."""

import argparse

from src.config import get_settings
from src.drive import DriveWatcher


def main():
    parser = argparse.ArgumentParser(
        description="Test Google Drive connection and list PDFs"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only list PDFs created in the past X days (default: all PDFs)",
    )
    args = parser.parse_args()

    print("Loading settings...")
    settings = get_settings()
    print(f"  Credentials: {settings.google_credentials_path}")
    print(f"  Folder ID: {settings.google_drive_folder_id}")

    print("\nConnecting to Google Drive...")
    watcher = DriveWatcher(
        credentials_path=settings.google_credentials_path,
        folder_id=settings.google_drive_folder_id,
    )

    if args.days:
        print(f"\nListing PDFs from the past {args.days} day(s)...")
    else:
        print("\nListing all PDFs in folder...")

    pdfs = watcher.list_pdfs(days_ago=args.days)

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
