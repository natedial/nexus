# Research Parser

A Python service that watches a Google Drive folder for financial research PDFs, extracts structured insights using LLMs, and stores results in Supabase PostgreSQL.

## Features

- **Google Drive Integration**: Polls a folder for new PDFs automatically
- **PDF Parsing**: Parses locally with Docling, optionally falls back to MinerU CLI, then LlamaIndex Cloud
- **Multi-Model Extraction**: Uses different LLM models optimized for each task
- **Extended Thinking**: Enables Claude's reasoning mode for complex analysis
- **Fault-Tolerant**: Each extraction step can fail independently without breaking the pipeline
- **Flexible Model Config**: Switch between Anthropic and OpenAI models via YAML config
- **Docker Ready**: Designed to run on Raspberry Pi or any Docker host

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Container (Pi)                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ Drive Watcher│──▶│ PDF Pipeline │──▶│ Supabase Client      │ │
│  │ (polling)    │   │              │   │                      │ │
│  └──────────────┘   └──────────────┘   └──────────────────────┘ │
│         │                  │                                     │
│         ▼                  ▼                                     │
│  ┌──────────────┐   ┌──────────────┐                            │
│  │ State Store  │   │ LLM Client   │                            │
│  │ (SQLite)     │   │ (Anthropic/  │                            │
│  └──────────────┘   │  OpenAI)     │                            │
│                     └──────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
         │                  │                    │
         ▼                  ▼                    ▼
    Google Drive   Docling / MinerU /      Supabase PostgreSQL
                     LlamaIndex Cloud
```

## Extraction Pipeline

| Step | Task | Default Model | Extended Thinking |
|------|------|---------------|-------------------|
| 1 | Strip boilerplate (legal disclaimers) | Haiku | No |
| 2 | Extract metadata (source, date, region) | Haiku | No |
| 3 | Extract themes (3-6 key themes) | Sonnet | Yes (8K tokens) |
| 4 | Extract trades (positioning ideas) | Sonnet | No |

> **Note**: Synthesis (through-lines connecting themes and trades) is performed downstream by [research_dispatcher](https://github.com/natedial/research_dispatcher), which aggregates results across multiple documents before synthesizing.

## Quick Start

### 1. Clone and Install

```bash
cd research_parser
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure Environment

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Required environment variables:

```env
# Google Drive
GOOGLE_CREDENTIALS_PATH=./credentials/service-account.json
GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here

# LLM APIs
ANTHROPIC_API_KEY=sk-ant-...  # Optional, only if using Anthropic models
OPENAI_API_KEY=sk-...  # Optional, only if using OpenAI models
GROQ_API_KEY=gsk_...  # Optional, only if using Groq models
DEEPINFRA_API_KEY=...  # Optional, only if using DeepInfra models
OPENROUTER_API_KEY=sk-or-...  # Optional, only if using OpenRouter models
FIREWORKS_API_KEY=...  # Optional, only if using Fireworks models
TOGETHER_API_KEY=...  # Optional, only if using Together models

# LlamaIndex Cloud
LLAMAINDEX_API_KEY=llx-...

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key

# Local paths (for development)
STATE_DB_PATH=./data/state.db

# Optional MinerU CLI fallback
MINERU_ENABLED=false
MINERU_BIN_PATH=/opt/mineru-venv/bin/mineru
MINERU_BACKEND=pipeline
MINERU_TIMEOUT_SECONDS=300

# Catchup on startup (process files from the last N days, 0 disables)
CATCHUP_DAYS=0
```

### 3. Set Up Google Drive

1. Create a service account in Google Cloud Console
2. Download the JSON credentials file
3. Share your Google Drive folder with the service account email
4. Set `GOOGLE_DRIVE_FOLDER_ID` to your folder's ID (from the URL)

### 4. Run

```bash
# Test the extraction pipeline
python scripts/test_extraction.py

# Run the full service
python -m src.main
```

To run in catchup mode, set `CATCHUP_DAYS` in `.env` before starting the service:

```bash
# Example: process the last 7 days on startup, then continue polling
export CATCHUP_DAYS=7
python -m src.main
```

Or run with a CLI flag to override the env setting:

```bash
python -m src.main --catchup 7
```

## Model Configuration

Models are configured in `config/models.yaml`. Change models without touching code:

```yaml
extraction:
  # Fast model for simple tasks
  boilerplate:
    provider: groq
    model: openai/gpt-oss-20b
    max_tokens: 4096
    temperature: 0
    fallback:
      - provider: deepinfra
        model: meta-llama/Llama-3.3-70B-Instruct-Turbo
        max_tokens: 4096
        temperature: 0

  # Smart model with reasoning for complex analysis
  themes:
    provider: openrouter
    model: openai/gpt-5.2
    max_tokens: 8192
    temperature: 0
    reasoning_effort: high
    fallback:
      - provider: deepinfra
        model: moonshotai/Kimi-K2-Instruct-0905
        max_tokens: 8192
        temperature: 0
```

## Optional MinerU Fallback

If you want an additional local parser before paying for LlamaIndex, you can install MinerU in a
separate virtualenv or via `pipx` and point the service at its CLI binary.

```bash
uv venv /opt/mineru-venv
/opt/mineru-venv/bin/uv pip install -U "mineru[all]"
```

Then configure:

```env
MINERU_ENABLED=true
MINERU_BIN_PATH=/opt/mineru-venv/bin/mineru
MINERU_BACKEND=pipeline
```

The parser order becomes:

```text
Docling -> MinerU CLI -> LlamaIndex
```

### Switching to OpenAI

```yaml
themes:
  provider: openai
  model: gpt-5.2
  max_tokens: 16000
  reasoning_effort: high

boilerplate:
  provider: openai
  model: gpt-4o-mini
  max_tokens: 8192
  temperature: 0
```

### Fallback Chains

Use `fallback` to route to a backup provider/model when the primary call fails:

```yaml
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

### Available Models

| Provider | Model | Best For | Thinking Support |
|----------|-------|----------|------------------|
| Anthropic | `claude-opus-4-5-20251101` | Complex reasoning, synthesis | Yes |
| Anthropic | `claude-sonnet-4-20250514` | Balanced tasks | Yes |
| Anthropic | `claude-3-5-haiku-20241022` | Fast, simple tasks | No |
| OpenAI | `gpt-4o` | General purpose | No |
| OpenAI | `gpt-4o-mini` | Fast, cheap | No |
| OpenAI | `gpt-5.2` | Complex reasoning | `reasoning_effort` |
| OpenAI | `o1` | Legacy reasoning | `reasoning_effort` |
| OpenAI | `o1-mini` | Faster legacy reasoning | `reasoning_effort` |
| Groq | `openai/gpt-oss-20b` | Low-cost extraction | No |
| Groq | `openai/gpt-oss-120b` | Higher-quality extraction | No |
| DeepInfra | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | Fallback or budget routing | No |

## Project Structure

```
research_parser/
├── config/
│   └── models.yaml          # Model configuration (edit this!)
├── prompts/
│   ├── boilerplate.md       # Prompt for stripping legal text
│   ├── metadata.md          # Prompt for metadata extraction
│   ├── themes.md            # Prompt for theme extraction
│   └── trades.md            # Prompt for trade extraction
├── src/
│   ├── config.py            # Environment settings
│   ├── llm.py               # Unified LLM client (Anthropic/OpenAI)
│   ├── pipeline.py          # Main orchestrator
│   ├── drive/
│   │   └── watcher.py       # Google Drive polling
│   ├── parser/
│   │   └── llamaindex.py    # PDF to markdown
│   ├── extraction/
│   │   ├── boilerplate.py   # Strip legal disclaimers
│   │   ├── metadata.py      # Extract source, date, region
│   │   ├── themes.py        # Extract key themes
│   │   ├── trades.py        # Extract trade ideas
│   │   ├── models.py        # Pydantic data models
│   │   └── prompts.py       # Prompt loader
│   └── storage/
│       ├── supabase.py      # Supabase client
│       └── state.py         # SQLite state tracking
├── scripts/
│   ├── test_drive.py        # Test Drive connection
│   ├── test_llamaindex.py   # Test PDF parsing
│   ├── test_extraction.py   # Test full extraction pipeline
│   └── test_supabase.py     # Test database connection
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Docker Deployment

### Build and Run

```bash
mkdir -p data credentials
docker compose up -d
```

Ensure `config/models.yaml` exists on the host (it is mounted into `/app/config` in the container).

If deploying on a fresh host, copy your model config into place:

```bash
cp /path/to/models.yaml ./config/models.yaml
```

### docker-compose.yml

```yaml
version: "3.8"
services:
  research-parser:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data              # SQLite state
      - ./credentials:/app/credentials:ro  # Google service account
      - ./config:/app/config:ro       # Model configuration
```

### Environment for Docker

Update `.env` for Docker paths:

```env
GOOGLE_CREDENTIALS_PATH=/app/credentials/service-account.json
STATE_DB_PATH=/app/data/state.db
```

## Fault Tolerance

The pipeline is designed to be resilient:

- **Per-step failure handling**: If metadata extraction fails, themes/trades still run
- **Partial results saved**: A document with themes but failed trades is still valuable
- **Boilerplate safeguard**: If stripping removes too much text, falls back to original
- **Null handling**: Missing fields in LLM responses get sensible defaults
- **Retry logic**: API calls retry with exponential backoff
- **State tracking**: SQLite tracks processed files to avoid reprocessing

## Extraction Output

## Checking Progress (SQLite)

The SQLite state database tracks each processed file and the status of every step.

```bash
# Status counts
sqlite3 ./data/state.db "SELECT status, COUNT(*) FROM processed_files GROUP BY status;"

# Latest 20 files with step flags
sqlite3 ./data/state.db "SELECT file_name, status, parse_ok, boilerplate_ok, metadata_ok, themes_ok, trades_ok, storage_ok, updated_at FROM processed_files ORDER BY updated_at DESC LIMIT 20;"
```

Each document produces structured JSON stored in Supabase:

```json
{
  "metadata": {
    "source": "Goldman Sachs Global Rates Trader",
    "source_date": "2025-12-19",
    "area": "USD",
    "region": "US",
    "asset_focus": "rates"
  },
  "themes": [
    {
      "label": "US Duration Strategy Outlook",
      "strength": "Primary",
      "confidence": "High",
      "excerpts": [...],
      "context": "..."
    }
  ],
  "trades": [
    {
      "text": "Front-end steepeners remain well positioned...",
      "conviction": "Medium",
      "timeframe": "months",
      "exposure": "Medium"
    }
  ]
}
```

## Development

### Run Tests

```bash
# Test individual components
python scripts/test_drive.py
python scripts/test_llamaindex.py
python scripts/test_extraction.py
python scripts/test_supabase.py

# Full pipeline test (processes one PDF)
python scripts/test_full_pipeline.py
```

### Customize Prompts

Edit the markdown files in `prompts/`:

- `boilerplate.md` - What to strip from documents
- `metadata.md` - What metadata fields to extract
- `themes.md` - How to identify and structure themes
- `trades.md` - How to identify trade recommendations

### Add a New Extraction Step

1. Create `src/extraction/newstep.py`
2. Add prompt to `prompts/newstep.md`
3. Add config to `config/models.yaml`
4. Wire into `src/pipeline.py`

## Troubleshooting

### "No PDFs found in folder"

- Ensure the folder is shared with your service account email
- Check the folder ID is correct (from the Drive URL)

### "Boilerplate result suspiciously short"

- The safeguard triggered because the model returned very little text
- The pipeline falls back to using the original markdown
- Consider adjusting the prompt in `prompts/boilerplate.md`

### "Failed to parse JSON"

- The LLM returned non-JSON text before the actual JSON
- The parser handles this by finding the first `[` or `{`
- If issues persist, check the prompt formatting

### Extended thinking not working

- Only works with Anthropic models that support it (Sonnet, Opus)
- Haiku does not support extended thinking
- OpenAI/OpenRouter reasoning uses `reasoning_effort`; keep it on themes, not metadata/trades

## License

MIT
