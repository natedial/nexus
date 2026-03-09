# Research Dispatch

Automated document analysis reporting system that queries a Supabase PostgreSQL database, formats research analysis, generates a styled PDF report, and emails it.

## Setup

### 1. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key

# Gmail SMTP (requires App Password)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@example.com

# Report
REPORT_TITLE=Research Dispatch

# Optional LLM providers for synthesis
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DEEPINFRA_API_KEY=

# Mode: debug (no DB updates) or production (marks docs as synthesized)
MODE=debug

# Filters (all optional - empty = no filter)
DATE_RANGE_DAYS=7
FILTER_SOURCES=
FILTER_REGION=
FILTER_ASSET_FOCUS=
CALENDAR_COUNTRY=US
```

### 4. Gmail App Password

Gmail requires an App Password (not your regular password):

1. Go to [Google Account Security](https://myaccount.google.com/security)
2. Enable 2-Step Verification
3. Search for "App passwords" in account settings
4. Create new app password for "Mail"
5. Use the 16-character password in `SMTP_PASSWORD`

## Usage

### Generate PDF only (no email)

```bash
python3 generate_pdf_only.py
```

### Full pipeline (PDF + email)

```bash
python3 src/main.py
```

### With filters

Set filters in `.env` to scope the report:

```bash
# US rates research only
FILTER_REGION=US
FILTER_ASSET_FOCUS=rates

# Specific sources
FILTER_SOURCES=Goldman Sachs,JP Morgan

# Last 3 days only
DATE_RANGE_DAYS=3
```

To route synthesis through DeepInfra, set `DEEPINFRA_API_KEY` and change the target entries in [`config/models.yaml`](/Users/ncdial/devwork/research_dispatcher/config/models.yaml) to `provider: deepinfra` with a supported model id such as `moonshotai/Kimi-K2.5` or `MiniMaxAI/MiniMax-M2.5`.

The cross-document synthesis workflow automatically appends the shared market analysis meta-lens in [`prompts/components/market_edge_lens.md`](/Users/ncdial/devwork/research_dispatcher/prompts/components/market_edge_lens.md) to monolithic synthesis and stage-one throughline generation, with a lighter callout lens in [`prompts/components/callout_selection_lens.md`](/Users/ncdial/devwork/research_dispatcher/prompts/components/callout_selection_lens.md).

The current stage-one priority order is:
- Stage 1 throughlines primary: `deepinfra:moonshotai/Kimi-K2-Instruct-0905`
- Fallback on request failure or bad JSON: `openai:gpt-5-mini`
- Secondary fallback if both above fail: `deepinfra:MiniMaxAI/MiniMax-M2.5`
- Stage 1B editor: `openai:gpt-5-mini` is the canonical editorial pass, rewriting stage-one output for readability and schema discipline without adding claims
- Stage 2 callouts: `openai:gpt-5-mini`

The canonical happy path is:
1. `Kimi-K2-Instruct` extracts the through-lines
2. `gpt-5-mini` edits those through-lines
3. `gpt-5-mini` extracts callouts
4. Fallbacks only apply when an earlier stage fails

The live stage-one workflow also honors compact request-shaping knobs in [`config/models.yaml`](/Users/ncdial/devwork/research_dispatcher/config/models.yaml): `prompt_profile`, `throughline_count`, `max_key_insight_words`, `max_supporting_themes`, `max_supporting_trades`, `payload_theme_limit`, and `payload_trade_limit`. This is how the tuned DeepInfra stage-one profiles are promoted into the actual workflow.

For the full migration record and model-role rationale, see [`docs/LLM_WORKFLOW_MIGRATION.md`](/Users/ncdial/devwork/research_dispatcher/docs/LLM_WORKFLOW_MIGRATION.md).

For quick provider checks without touching the database or full report pipeline, run [`smoke_test_deepinfra.py`](/Users/ncdial/devwork/research_dispatcher/smoke_test_deepinfra.py):

```bash
.venv/bin/python smoke_test_deepinfra.py --mode raw
.venv/bin/python smoke_test_deepinfra.py --mode throughline --model moonshotai/Kimi-K2.5 --timeout 90 --retries 1
.venv/bin/python smoke_test_deepinfra.py --mode throughline --model moonshotai/Kimi-K2.5 --json-object --drop-response-format-on-retry --tool-choice none --reasoning-effort none
```

For non-instruct / more agentic DeepInfra models such as `moonshotai/Kimi-K2.5` or `MiniMaxAI/MiniMax-M2.5`, prefer:
- `response_format: {type: json_object}`
- `tool_choice: none`
- `reasoning_effort: none`
- `drop_response_format_on_retry: true`

For instruct models such as `moonshotai/Kimi-K2-Instruct-0905`, prefer `response_format: {type: json_object}` first, but do not force the extra agentic flags unless testing shows they help.

Filter options:
- `FILTER_REGION`: US, EU, UK, Japan, China, EM, Global
- `FILTER_ASSET_FOCUS`: rates, credit, FX, equities, commodities, multi-asset
- `FILTER_SOURCES`: Comma-separated list of source names
- `DATE_RANGE_DAYS`: Number of days to look back

### Production mode

Set `MODE=production` to mark processed documents as synthesized (prevents re-processing):

```bash
MODE=production
```

## Scheduling

### macOS (launchd)

```bash
# Edit the plist
nano ~/Library/LaunchAgents/com.research.dispatch.plist
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.research.dispatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python3</string>
        <string>/path/to/research_dispatcher/src/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/research_dispatcher</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.research.dispatch.plist
```

### Linux/cron

```bash
crontab -e
```

```
# Run daily at 9 AM
0 9 * * * cd /path/to/research_dispatcher && /path/to/venv/bin/python3 src/main.py
```

## Project Structure

```
research_dispatcher/
├── config.py              # Configuration from environment
├── format_rules.yaml      # PDF styling (colors, fonts, spacing)
├── generate_pdf_only.py   # PDF generation without email
├── requirements.txt       # Python dependencies
├── .env                   # Your credentials (not in git)
├── .env.example           # Template for .env
└── src/
    ├── main.py            # Full pipeline orchestration
    ├── database.py        # Supabase queries
    ├── formatter.py       # Data formatting and aggregation
    ├── pdf_generator.py   # PDF generation with ReportLab
    └── email_sender.py    # SMTP email delivery
```

## Customization

### PDF Styling

Edit `format_rules.yaml` to change colors, fonts, and spacing:

```yaml
TITLE:
  - font_size: 48
    font_color: '#000000'

H1_HEADING:
  - font_size: 28
    font_color: '#FF4458'  # Coral red

ACCENT_COLOR:
  - color: '#FF4458'
```

### Database Schema

The system expects a `parsed_research` table with:
- `source_date` - Document date
- `source` - Publisher/source name
- `parsed_data` - JSONB containing:
  - `metadata` (region, asset_focus, etc.)
  - `themes`
  - `trades`
  - `through_lines`
  - `callouts`

Calendar tables (`economic_events`, `supply_events`) are optional.
