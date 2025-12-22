import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Supabase
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')

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

    # Filters
    DATE_RANGE_DAYS = int(os.getenv('DATE_RANGE_DAYS', 3))  # Number of days to look back
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
