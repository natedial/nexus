import os
from dotenv import load_dotenv

load_dotenv()


def _int_from_env(name: str, default: int) -> int:
    """Parse int env var, falling back to default on empty/invalid values."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Config:
    """Application configuration loaded from environment variables."""

    # Supabase
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

    # LLM API Keys (for cross-document synthesis)
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')  # Optional

    # Synthesis toggle
    ENABLE_SYNTHESIS = os.getenv('ENABLE_SYNTHESIS', 'true').lower() in ('true', '1', 'yes')

    # Email
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    EMAIL_FROM = os.getenv('EMAIL_FROM')
    EMAIL_TO = os.getenv('EMAIL_TO')

    # Report
    REPORT_TITLE = os.getenv('REPORT_TITLE', 'Document Analysis Report')

    # Mode: debug (doesn't update synthesized) or production (updates synthesized)
    MODE = os.getenv('MODE', 'debug').lower()

    # Feedback links (Supabase Edge Function)
    FEEDBACK_BASE_URL = os.getenv(
        'FEEDBACK_BASE_URL',
        'https://qeyhmsqepsenhvtkryjh.supabase.co/functions/v1/feedback'
    )

    # Document viewer (static HTML page on S3)
    DOCUMENT_VIEWER_URL = os.getenv(
        'DOCUMENT_VIEWER_URL',
        'http://research-dispatch-viewer.s3-website-us-east-1.amazonaws.com/document-viewer.html'
    )
    DOCUMENT_LINK_SECRET = os.getenv('DOCUMENT_LINK_SECRET', '')
    DOCUMENT_LINK_TTL_DAYS = _int_from_env('DOCUMENT_LINK_TTL_DAYS', 7)

    # Filters
    DATE_RANGE_DAYS = _int_from_env('DATE_RANGE_DAYS', 3)  # Number of days to look back
    FILTER_SOURCES = os.getenv('FILTER_SOURCES', '')  # Comma-separated list of sources (empty = all)
    FILTER_REGION = os.getenv('FILTER_REGION', '')  # Filter by region: US, EU, UK, Japan, China, EM, Global (empty = all)
    FILTER_ASSET_FOCUS = os.getenv('FILTER_ASSET_FOCUS', '')  # Filter by asset: rates, credit, FX, equities, commodities, multi-asset (empty = all)
    CALENDAR_COUNTRY = os.getenv('CALENDAR_COUNTRY', 'US')  # Country for calendar events

    @classmethod
    def validate(cls):
        """Validate that all required configuration is present."""
        required = [
            'SUPABASE_URL', 'SUPABASE_KEY',
            'SMTP_USERNAME', 'SMTP_PASSWORD',
            'EMAIL_FROM', 'EMAIL_TO'
        ]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
