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
