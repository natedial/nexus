#!/usr/bin/env python3
"""Inspect the state database."""

import argparse
import os
import sqlite3
from pathlib import Path


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


def _parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_db_path(cli_db_path: str | None) -> Path:
    if cli_db_path:
        return Path(cli_db_path).expanduser()

    env_value = os.getenv("STATE_DB_PATH")
    if env_value:
        return Path(env_value).expanduser()

    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / ".env"
    env_values = _parse_env_file(env_path)
    env_db = env_values.get("STATE_DB_PATH")
    if env_db:
        env_path_value = Path(env_db).expanduser()
        return env_path_value if env_path_value.is_absolute() else repo_root / env_path_value

    default_local = repo_root / "data" / "state.db"
    if default_local.exists():
        return default_local

    return Path("/app/data/state.db")


def main():
    parser = argparse.ArgumentParser(description="Inspect state database")
    parser.add_argument(
        "--db",
        help="Path to SQLite state database (overrides STATE_DB_PATH/.env)",
    )
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

    db_path = resolve_db_path(args.db)

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
