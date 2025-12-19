# Research Dispatch

Automated document analysis reporting system that queries a Supabase PostgreSQL database, formats the results, generates a PDF report, and emails it.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. For Gmail, create an App Password:
   - Go to Google Account settings
   - Security > 2-Step Verification > App passwords
   - Generate a new app password and use it in SMTP_PASSWORD

## Usage

Run manually:
```bash
python src/main.py
```

Schedule with cron (runs daily at 9 AM):
```bash
crontab -e
# Add: 0 9 * * * cd ~/dev/research-dispatch && /path/to/venv/bin/python src/main.py
```

## Project Structure

- `src/database.py` - Supabase connection and queries
- `src/formatter.py` - Data formatting logic
- `src/pdf_generator.py` - PDF generation
- `src/email_sender.py` - Email delivery
- `src/main.py` - Main orchestration script
- `config.py` - Configuration management
