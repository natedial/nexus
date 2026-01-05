#!/usr/bin/env python3
"""Inspect the state database."""

import argparse
import sqlite3
from pathlib import Path

from src.config import get_settings


def print_table(headers, rows, max_width=50):
    """Simple table printer without external dependencies."""
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], min(len(str(val)), max_width))

    # Print header
    header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in widths)
    print(header_line)
    print(separator)

    # Print rows
    for row in rows:
        row_vals = []
        for i, val in enumerate(row):
            val_str = str(val) if val is not None else ""
            if len(val_str) > max_width:
                val_str = val_str[:max_width - 3] + "..."
            row_vals.append(val_str.ljust(widths[i]))
        print(" | ".join(row_vals))
    print()


def main():
    parser = argparse.ArgumentParser(description="Inspect state database")
    parser.add_argument(
        "--status",
        choices=["pending", "parsing", "extracting", "completed", "failed", "partial"],
        help="Filter by status",
    )
    parser.add_argument(
        "--failed",
        action="store_true",
        help="Show only failed and partial files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Limit number of rows (default: 20)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all columns including step flags",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_path = settings.state_db_path

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Build query
        if args.verbose:
            columns = "file_name, status, created_at, updated_at, parse_ok, boilerplate_ok, metadata_ok, themes_ok, trades_ok, storage_ok, error_message"
        elif args.failed:
            # Include error_message when showing failed files
            columns = "file_name, status, updated_at, error_message"
        else:
            columns = "file_name, status, updated_at"

        where_clause = ""
        params = []

        if args.failed:
            where_clause = "WHERE status IN ('failed', 'partial')"
        elif args.status:
            where_clause = "WHERE status = ?"
            params.append(args.status)

        query = f"""
            SELECT {columns}
            FROM processed_files
            {where_clause}
            ORDER BY updated_at DESC
            LIMIT ?
        """
        params.append(args.limit)

        rows = conn.execute(query, params).fetchall()

        if not rows:
            print("No records found.")
            return

        # Print summary
        summary_query = "SELECT status, COUNT(*) as count FROM processed_files GROUP BY status"
        summary = conn.execute(summary_query).fetchall()

        print("\n=== Database Summary ===")
        print(f"Location: {db_path}\n")
        summary_data = [(row["status"], row["count"]) for row in summary]
        print_table(["Status", "Count"], summary_data)

        # Print records
        print(f"=== Records (showing {len(rows)}) ===\n")

        # Convert rows to list of lists
        headers = list(rows[0].keys())
        data = []
        for row in rows:
            row_data = []
            for col in headers:
                val = row[col]
                # Format booleans
                if isinstance(val, int) and col.endswith("_ok"):
                    val = "✓" if val == 1 else "✗" if val == 0 else "-"
                row_data.append(val if val is not None else "")
            data.append(row_data)

        print_table(headers, data)

        # Show errors if any
        if args.failed or args.verbose:
            errors = [
                (row["file_name"], row["error_message"])
                for row in rows
                if row["error_message"] is not None and row["error_message"] != ""
            ]
            if errors:
                print("=== Error Messages ===\n")
                for fname, error in errors:
                    print(f"{fname}:")
                    print(f"  {error}\n")


if __name__ == "__main__":
    main()
