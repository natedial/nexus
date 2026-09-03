# Reviewing the State Database

This guide explains how to inspect and review the `state.db` SQLite database that tracks processing status for all PDFs.

## Quick Reference

### Command-Line (Fastest)

```bash
# View recent files
sqlite3 data/state.db "SELECT file_name, status, updated_at FROM processed_files ORDER BY updated_at DESC LIMIT 10;"

# View with step details
sqlite3 -header -column data/state.db "SELECT file_name, status, parse_ok, boilerplate_ok, storage_ok FROM processed_files ORDER BY updated_at DESC LIMIT 10;"

# Count by status
sqlite3 data/state.db "SELECT status, COUNT(*) FROM processed_files GROUP BY status;"

# Show only failed/partial
sqlite3 -header -column data/state.db "SELECT file_name, status, error_message FROM processed_files WHERE status IN ('failed', 'partial');"
```

## Inspection Script (Recommended)

The project includes a helper script for easy database inspection:

```bash
# Basic view (recent 20 files)
python3 scripts/inspect_state.py

# Show all details including step flags
python3 scripts/inspect_state.py -v

# Show only failed files
python3 scripts/inspect_state.py --failed

# Filter by status
python3 scripts/inspect_state.py --status completed

# Show more records
python3 scripts/inspect_state.py --limit 50

# Get help
python3 scripts/inspect_state.py --help
```

### Example Output

```
=== Database Summary ===
Location: /path/to/data/state.db

Status    | Count
----------+------
completed | 15
partial   | 3
failed    | 1

=== Records (showing 10) ===

file_name              | status    | updated_at
-----------------------+-----------+----------------------------
Research_Report_Q4.pdf | completed | 2026-01-01T12:34:56
Analysis_2025.pdf      | partial   | 2026-01-01T12:30:12
```

## Interactive SQLite Shell

```bash
sqlite3 data/state.db

# In the shell:
.headers on
.mode column
SELECT * FROM processed_files ORDER BY updated_at DESC LIMIT 5;
.quit
```

## Database Schema

The `processed_files` table contains:

| Column | Type | Description |
|--------|------|-------------|
| `file_id` | TEXT | Google Drive file ID (primary key) |
| `file_name` | TEXT | Original filename |
| `status` | TEXT | Processing status (see below) |
| `created_at` | TEXT | When processing started (ISO timestamp) |
| `updated_at` | TEXT | Last update timestamp (ISO timestamp) |
| `parse_ok` | INTEGER | PDF parsing success (1=success, 0=failed, NULL=not run) |
| `boilerplate_ok` | INTEGER | Boilerplate stripping success |
| `metadata_ok` | INTEGER | Legacy column from the old extraction worker |
| `themes_ok` | INTEGER | Legacy column from the old extraction worker |
| `trades_ok` | INTEGER | Legacy column from the old extraction worker |
| `storage_ok` | INTEGER | Supabase storage success |
| `error_message` | TEXT | Error details if any |

### Status Values

- `pending` - File queued for processing
- `parsing` - Currently parsing PDF to markdown
- `storing` - Writing `parsed_research` and memory tables
- `extracting` - Legacy in-progress rows from the old extraction worker
- `completed` - Parse, clean, and storage succeeded
- `partial` - Some steps succeeded, some failed
- `failed` - Fatal failure (e.g., PDF parsing failed)

## Common Queries

### Files processed in the last 24 hours
```sql
SELECT file_name, status, updated_at
FROM processed_files
WHERE updated_at > datetime('now', '-1 day')
ORDER BY updated_at DESC;
```

### Files with storage failures
```sql
SELECT file_name, error_message
FROM processed_files
WHERE storage_ok = 0;
```

### Success rate by step
```sql
SELECT
    SUM(parse_ok) as parse_success,
    SUM(boilerplate_ok) as boilerplate_success,
    SUM(storage_ok) as storage_success,
    COUNT(*) as total
FROM processed_files;
```

### Files that need retry
```sql
SELECT file_name, status, error_message
FROM processed_files
WHERE status = 'failed'
ORDER BY updated_at DESC;
```

## GUI Tools (Optional)

For a visual interface, you can use:

### Free Options
- **DB Browser for SQLite** (recommended)
  - Download: https://sqlitebrowser.org/
  - Cross-platform, easy to use
  - Can browse, edit, and query

- **DBeaver Community**
  - Download: https://dbeaver.io/
  - Universal database tool

- **SQLiteStudio**
  - Download: https://sqlitestudio.pl/
  - Lightweight and portable

### macOS Specific
- **TablePlus** (free tier available)
  - Download: https://tableplus.com/
  - Modern, clean interface

Simply open `data/state.db` in any of these tools.

## Troubleshooting

### Database locked error
If you get "database is locked", the service is probably running. Stop the service first:
```bash
docker compose down
# or if running locally
pkill -f "python -m src.main"
```

### Database not found
Make sure you're in the project root directory. The default path is:
```
data/state.db
```

You can check the configured path with:
```python
from src.config import get_settings
print(get_settings().state_db_path)
```

## Related Documentation

- [Pipeline Architecture](../CLAUDE.md#architecture) - How processing works
- [Warning Capture](./warning-capture.md) - Reviewing parse and storage warnings
- [State Management](../src/storage/state.py) - State tracking implementation
