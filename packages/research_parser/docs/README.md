# Research Parser Documentation

Additional documentation for the financial research parser system.

## Guides

### [Reviewing State Database](./reviewing-state-database.md)
Learn how to inspect and query the `state.db` SQLite database that tracks processing status for all PDFs.

**Quick commands:**
- View recent files: `python3 scripts/inspect_state.py`
- Show failures: `python3 scripts/inspect_state.py --failed`
- All details: `python3 scripts/inspect_state.py -v`

### [Warning Capture System](./warning-capture.md)
Understand how warnings are automatically captured to files for debugging parse and storage issues.

**Key locations:**
- Warning files: `data/warnings/`
- Test system: `python3 scripts/test_warning_capture.py`

### [Release Checklist](./release-checklist.md)
Quality gates and pre-deploy validation steps.

## Architecture Overview

For architecture and build instructions, see the main [CLAUDE.md](../CLAUDE.md) file in the project root.

### Processing Pipeline

```
Drive Watcher → Docling / optional MinerU → Deterministic clean
                                          → Source artifacts + spans
                                          → Supabase parsed_research
```

This service owns parse and source storage. Theme/trade extraction belongs in another service.

## Useful Scripts

Located in `scripts/`:

| Script | Purpose |
|--------|---------|
| `test_drive.py` | Test Google Drive connection and list PDFs |
| `test_full_pipeline.py` | Run full pipeline on up to 3 PDFs |
| `inspect_state.py` | Inspect state database |
| `test_warning_capture.py` | Test warning capture system |
| `verify_live_document_identity.py` | Live Supabase smoke test for parser upsert identity |

### Script Usage Examples

```bash
# List PDFs from the past 7 days
python3 scripts/test_drive.py --days 7

# Verify live parsed_research upsert identity after applying migration 005
python3 scripts/verify_live_document_identity.py

# Process up to 3 new PDFs
python3 scripts/test_full_pipeline.py

# View processing state
python3 scripts/inspect_state.py --limit 10
```

## Configuration

Parse-and-store is configured with environment variables (see `.env.example`).

Required vars:

```env
GOOGLE_CREDENTIALS_PATH=./credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_key
```

## Data Storage

The system creates these directories in `data/`:

```
data/
├── artifacts/         # Per-document parse artifacts
├── warnings/          # Captured parse/storage warnings
├── state.db           # Processing state database
└── (temp files)       # Downloaded PDFs (cleaned up automatically)
```

These are excluded from git via `.gitignore`.

## Troubleshooting

### Common Issues

**Database locked**
```bash
# Stop the service first
docker compose down
```

**No PDFs found**
```bash
# Test Drive connection
python3 scripts/test_drive.py

# Check folder ID in .env
echo $GOOGLE_DRIVE_FOLDER_ID
```

**Parse or storage failures**
```bash
# Check warnings
ls -lh data/warnings/

# Review state
python3 scripts/inspect_state.py --failed
```

## Getting Help

1. Check relevant documentation above
2. Review logs: `docker compose logs -f`
3. Inspect state database for specific errors
4. Review warning files for parse/storage issues

## Contributing

When adding new features:

1. Update relevant documentation in `docs/`
2. Add test scripts to `scripts/` if applicable
3. Update `CLAUDE.md` for architecture changes
4. Document configuration changes in this README
