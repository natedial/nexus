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
Understand how warnings are automatically captured to files for debugging extraction issues.

**Key locations:**
- Warning files: `data/warnings/`
- Test system: `python3 scripts/test_warning_capture.py`

## Architecture Overview

For architecture and build instructions, see the main [CLAUDE.md](../CLAUDE.md) file in the project root.

### Processing Pipeline

```
Drive Watcher → LlamaIndex Parser → Extraction Chain → Supabase Storage
                                    ├─ Strip boilerplate
                                    ├─ Extract metadata
                                    ├─ Extract themes
                                    └─ Extract trades
```

Each step is fault-tolerant - if one fails, processing continues with defaults and the failure is tracked.

## Useful Scripts

Located in `scripts/`:

| Script | Purpose |
|--------|---------|
| `test_drive.py` | Test Google Drive connection and list PDFs |
| `test_extraction.py` | Test extraction pipeline on a single PDF |
| `test_full_pipeline.py` | Run full pipeline on up to 3 PDFs |
| `inspect_state.py` | Inspect state database |
| `test_warning_capture.py` | Test warning capture system |

### Script Usage Examples

```bash
# List PDFs from the past 7 days
python3 scripts/test_drive.py --days 7

# Test extraction on first PDF
python3 scripts/test_extraction.py

# Process up to 3 new PDFs
python3 scripts/test_full_pipeline.py

# View processing state
python3 scripts/inspect_state.py --limit 10
```

## Configuration

All configuration is in `config/models.yaml`:

- **Model selection**: Choose Claude vs OpenAI models per step
- **Extended thinking**: Enable/disable reasoning for complex steps
- **Token limits**: Adjust max_tokens per extraction step
- **Temperature**: Control randomness (0 = deterministic)

Example:
```yaml
extraction:
  themes:
    provider: anthropic
    model: claude-sonnet-4-5-20250929
    max_tokens: 16000
    extended_thinking:
      enabled: true
      budget_tokens: 8000
```

## Environment Variables

Required variables (set in `.env`):

```bash
# Google Drive
GOOGLE_CREDENTIALS_PATH=./credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id

# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...
LLAMAINDEX_API_KEY=llx-...

# Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_key
```

## Data Storage

The system creates these directories in `data/`:

```
data/
├── warnings/          # Captured extraction warnings
├── state.db          # Processing state database
└── (temp files)      # Downloaded PDFs (cleaned up automatically)
```

Both are excluded from git via `.gitignore`.

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

**Extraction failures**
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
4. Review warning files for extraction issues

## Contributing

When adding new features:

1. Update relevant documentation in `docs/`
2. Add test scripts to `scripts/` if applicable
3. Update `CLAUDE.md` for architecture changes
4. Document configuration changes in this README
