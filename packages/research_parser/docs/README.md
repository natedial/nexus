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

### [Release Checklist](./release-checklist.md)
Quality gates and pre-deploy validation steps.

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
| `compare_baseline.py` | Record/compare extraction baselines |
| `verify_live_document_identity.py` | Live Supabase smoke test for parser upsert identity |

### Script Usage Examples

```bash
# List PDFs from the past 7 days
python3 scripts/test_drive.py --days 7

# Test extraction on first PDF
python3 scripts/test_extraction.py

# Verify live parsed_research upsert identity after applying migration 005
python3 scripts/verify_live_document_identity.py

# Process up to 3 new PDFs
python3 scripts/test_full_pipeline.py

# View processing state
python3 scripts/inspect_state.py --limit 10
```

## Configuration

All configuration is in `config/models.yaml`:

- **Model selection**: Choose provider/model per step (Anthropic, OpenAI, Groq, etc.)
- **Fallback routing**: Optional `fallback` list for backup providers/models
- **Extended thinking**: Enable Anthropic thinking for complex steps
- **Reasoning effort**: Explicitly set OpenAI/OpenRouter reasoning effort for complex steps
- **Token limits**: Adjust max_tokens per extraction step
- **Temperature**: Control randomness (0 = deterministic)

Example:
```yaml
extraction:
  themes:
    provider: groq
    model: openai/gpt-oss-120b
    max_tokens: 8192
    temperature: 0
    fallback:
      - provider: deepinfra
        model: meta-llama/Llama-3.3-70B-Instruct-Turbo
        max_tokens: 8192
        temperature: 0
```

Use reasoning only where the task needs multi-pass analysis. In this repo, that means
`themes` when quality is more important than cost/latency:

```yaml
extraction:
  themes:
    provider: openrouter
    model: openai/gpt-5.2
    max_tokens: 8192
    reasoning_effort: high
    fallback:
      - provider: deepinfra
        model: moonshotai/Kimi-K2-Instruct-0905
        max_tokens: 8192
        temperature: 0
```

## Environment Variables

Environment variables (set in `.env`):

```bash
# Google Drive
GOOGLE_CREDENTIALS_PATH=./credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id

# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...  # Optional, only for Anthropic models
OPENAI_API_KEY=sk-...  # Optional, only for OpenAI models
GROQ_API_KEY=gsk_...  # Optional, only for Groq models
DEEPINFRA_API_KEY=...  # Optional, only for DeepInfra models
OPENROUTER_API_KEY=sk-or-...  # Optional, only for OpenRouter models
FIREWORKS_API_KEY=...  # Optional, only for Fireworks models
TOGETHER_API_KEY=...  # Optional, only for Together models
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
