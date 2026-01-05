# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Research Dispatch is an automated research document analysis and reporting system. It:
- Queries a Supabase PostgreSQL database for parsed research documents
- Runs LLM-powered cross-document synthesis to extract common themes and actionable trades
- Generates styled PDF reports using ReportLab
- Emails reports via Gmail SMTP
- Tracks processing state to avoid re-processing documents

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Running the Application
```bash
# Generate PDF only (no email, no database updates)
python3 generate_pdf_only.py

# Full pipeline (PDF + email + database marking in production mode)
python3 src/main.py
```

### Testing Database Queries
```bash
# Test database connection and query
python3 test_query.py
```

## Architecture

### Pipeline Flow

1. **Database Query** (`database.py` → `DatabaseClient`)
   - Queries `parsed_research` table with filters (date range, source, region, asset_focus)
   - Queries `economic_events` and `supply_events` for upcoming week calendar
   - Filters use JSONB operators to query nested `parsed_data->metadata` fields

2. **Cross-Document Synthesis** (`synthesizer.py` → `Synthesizer`)
   - Extracts themes and trades from all documents
   - Calls LLM via unified client (`llm.py` → `LLMClient`)
   - Uses prompt from `prompts/synthesis.md`
   - Produces cross-document through-lines and callouts (replaces per-document aggregation)
   - Handles both Anthropic (with extended thinking) and OpenAI models

3. **Data Formatting** (`formatter.py` → `ReportFormatter`)
   - Aggregates themes by label/strength
   - Aggregates trades by conviction/timeframe
   - Formats calendar events by day
   - If synthesis ran: synthesis through-lines/callouts replace per-document ones

4. **PDF Generation** (`pdf_generator.py` → `PDFGenerator`)
   - Reads styling from `format_rules.yaml`
   - Generates multi-section report with ReportLab
   - Includes feedback links to Supabase Edge Function

5. **Email Delivery** (`email_sender.py` → `EmailSender`)
   - Sends via Gmail SMTP (requires App Password)
   - Supports multiple recipients (comma-separated EMAIL_TO)

6. **Database Update** (`database.py` → `mark_as_synthesized()`)
   - Only in production mode (`MODE=production`)
   - Sets `synthesized=true` flag to prevent re-processing

### Key Design Patterns

**Mode System**: `MODE` environment variable controls behavior
- `debug` (default): Queries DB, runs synthesis, generates PDF, sends email, but DOES NOT mark documents as synthesized
- `production`/`prod`/`active`: Full pipeline including database updates

**LLM Abstraction**: Unified `LLMClient` supports both Anthropic and OpenAI
- Model selection via `config/models.yaml`
- Extended thinking (Anthropic) or reasoning models (OpenAI o1/o3) for synthesis
- Lazy-loads clients only when needed

**Filter System**: All filters are optional (empty = all)
- `DATE_RANGE_DAYS`: Days to look back (default: 7)
- `FILTER_SOURCES`: Comma-separated source names
- `FILTER_REGION`: US, EU, UK, Japan, China, EM, Global
- `FILTER_ASSET_FOCUS`: rates, credit, FX, equities, commodities, multi-asset
- Active filters are displayed in generated reports

**Synthesis Toggle**: `ENABLE_SYNTHESIS=true/false` controls LLM synthesis
- When enabled: Cross-document synthesis replaces per-document through-lines
- When disabled: Falls back to aggregating per-document through-lines
- Requires `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`

### Database Schema

The system expects:
- `parsed_research` table with:
  - `id`, `source`, `document_name`, `source_date`, `parsed_at`
  - `parsed_data` (JSONB) containing:
    - `metadata` (region, asset_focus, publisher, etc.)
    - `themes` (array of {label, context, strength, confidence})
    - `trades` (array of {text, conviction, timeframe, rationale})
    - `through_lines` (array of {lead, detail, source, document})
    - `callouts` (array of {content, source, tags})
  - `synthesized` (boolean flag)

- `economic_events` table with:
  - `event_date`, `time_ny`, `event_name`, `consensus`, `importance_indicator`, `country`

- `supply_events` table with:
  - `event_date`, `time_ny`, `description`, `size_bn`, `maturity`, `country`

Calendar queries use `_get_upcoming_week_range()` to fetch Monday-Friday of next week.

### Configuration Files

**`.env`**: All runtime configuration (credentials, filters, mode)
- See `.env.example` for template
- Never commit this file

**`format_rules.yaml`**: PDF styling (colors, fonts, spacing)
- Based on Design Genome Project aesthetic (coral red, black, white)
- Modular rules for titles, headings, text, tables

**`config/models.yaml`**: LLM model selection
- Change models without code changes
- Supports extended thinking (Anthropic) configuration
- Reference list of available models

**`prompts/synthesis.md`**: Cross-document synthesis prompt
- Used by `Synthesizer` to generate through-lines and callouts
- Expects JSON output with specific schema

## Important Notes

### Gmail SMTP Setup
Gmail requires an App Password (not regular password):
1. Enable 2-Step Verification in Google Account
2. Generate App Password for "Mail"
3. Use 16-character password in `SMTP_PASSWORD`

### Production Deployment
When deploying to production:
- Set `MODE=production` to enable database updates
- Use scheduling (macOS launchd or Linux cron) - see `SCHEDULING.md`
- Ensure virtual environment paths are absolute in scheduler config

### Adding New Filters
To add a new filter:
1. Add environment variable to `.env.example` and `config.py`
2. Add filter logic in `database.py` → `query_analysis()`
3. Add to `active_filters` dict in `main.py` and `generate_pdf_only.py`
4. Formatter will automatically display in report metadata

### Changing LLM Models
Edit `config/models.yaml` → `synthesis` section:
- For Anthropic: Enable `extended_thinking` for models that support it
- For OpenAI: Use `o1`/`o1-mini` for reasoning or `gpt-4o`/`gpt-5.2` for general
- Temperature is ignored for reasoning models
