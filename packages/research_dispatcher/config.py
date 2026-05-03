import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

VALID_TRADE_CONVICTION_FILTERS = {"high", "medium", "all"}
VALID_DISPATCH_INPUT_MODES = {"parser", "analyst"}


def _int_from_env(name: str, default: int) -> int:
    """Parse int env var, falling back to default on empty/invalid values."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_trade_conviction_filter(raw: str | None, default: str = "high") -> str:
    """Normalize the trade conviction filter and fail fast on invalid values."""
    candidate = (raw or "").strip().lower()
    if not candidate:
        return default
    if candidate == "low":
        return "all"
    if candidate in VALID_TRADE_CONVICTION_FILTERS:
        return candidate
    raise ValueError("FILTER_TRADE_CONVICTION must be one of: high, medium, all")


def parse_dispatch_input_mode(raw: str | None, default: str = "parser") -> str:
    """Normalize dispatcher input mode and fail fast on invalid values."""
    candidate = (raw or "").strip().lower()
    if not candidate:
        return default
    if candidate in VALID_DISPATCH_INPUT_MODES:
        return candidate
    raise ValueError("DISPATCH_INPUT_MODE must be one of: parser, analyst")


def _is_https_url(value: str | None) -> bool:
    """Return True when the value is a valid HTTPS URL."""
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


class Config:
    """Application configuration loaded from environment variables."""

    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    # LLM API Keys (for cross-document synthesis)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Optional
    DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")  # Optional
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Optional

    # Synthesis toggle
    ENABLE_SYNTHESIS = os.getenv("ENABLE_SYNTHESIS", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    # Skill-based pipeline (two-stage synthesis instead of monolithic prompt)
    USE_SKILL_PIPELINE = os.getenv("USE_SKILL_PIPELINE", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    # Email
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    EMAIL_FROM = os.getenv("EMAIL_FROM")
    EMAIL_TO = os.getenv("EMAIL_TO")

    # Report
    REPORT_TITLE = os.getenv("REPORT_TITLE", "Document Analysis Report")
    DISPATCH_INPUT_MODE = parse_dispatch_input_mode(os.getenv("DISPATCH_INPUT_MODE"))
    ANALYST_BATCH_PATH = os.getenv("ANALYST_BATCH_PATH", "").strip()
    DISPATCH_DB_PATH = os.getenv(
        "DISPATCH_DB_PATH", os.path.join("state", "dispatch_history.db")
    )

    # Mode: debug (doesn't update synthesized) or production (updates synthesized)
    MODE = os.getenv("MODE", "debug").lower()
    LEGACY_SYNTHESIZED_UPDATES = os.getenv(
        "LEGACY_SYNTHESIZED_UPDATES",
        "false",
    ).lower() in ("true", "1", "yes")

    # Feedback links (Supabase Edge Function)
    FEEDBACK_BASE_URL = os.getenv(
        "FEEDBACK_BASE_URL",
        "https://qeyhmsqepsenhvtkryjh.supabase.co/functions/v1/feedback",
    )

    # Document viewer (static HTML page on S3)
    DOCUMENT_VIEWER_URL = os.getenv(
        "DOCUMENT_VIEWER_URL",
        "http://research-dispatch-viewer.s3-website-us-east-1.amazonaws.com/document-viewer.html",
    )
    DOCUMENT_LINK_SECRET = os.getenv("DOCUMENT_LINK_SECRET", "")
    DOCUMENT_LINK_TTL_DAYS = _int_from_env("DOCUMENT_LINK_TTL_DAYS", 7)

    # Filters
    DATE_RANGE_DAYS = _int_from_env("DATE_RANGE_DAYS", 3)  # Number of days to look back
    FILTER_SOURCES = os.getenv(
        "FILTER_SOURCES", ""
    )  # Comma-separated list of sources (empty = all)
    FILTER_REGION = os.getenv(
        "FILTER_REGION", ""
    )  # Filter by region: US, EU, UK, Japan, China, EM, Global (empty = all)
    FILTER_ASSET_FOCUS = os.getenv(
        "FILTER_ASSET_FOCUS", ""
    )  # Filter by asset: rates, credit, FX, equities, commodities, multi-asset (empty = all)
    FILTER_TRADE_CONVICTION = parse_trade_conviction_filter(
        os.getenv("FILTER_TRADE_CONVICTION", "high")
    )  # Filter trades: high, medium, all (default: high; low aliases to all)
    CALENDAR_COUNTRY = os.getenv(
        "CALENDAR_COUNTRY", "US"
    )  # Country for calendar events

    # Interactive links (feedback and document viewer)
    FEEDBACK_ENABLED = os.getenv("FEEDBACK_ENABLED", "false").lower() == "true"

    @classmethod
    def validate(cls):
        """Validate that all required configuration is present."""
        required = [
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "EMAIL_FROM",
            "EMAIL_TO",
        ]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        cls.DISPATCH_INPUT_MODE = parse_dispatch_input_mode(cls.DISPATCH_INPUT_MODE)
        if cls.DISPATCH_INPUT_MODE == "analyst":
            if not cls.ANALYST_BATCH_PATH:
                raise ValueError(
                    "ANALYST_BATCH_PATH is required when DISPATCH_INPUT_MODE=analyst"
                )
            if not os.path.isfile(cls.ANALYST_BATCH_PATH) or not os.access(
                cls.ANALYST_BATCH_PATH, os.R_OK
            ):
                raise ValueError(
                    "ANALYST_BATCH_PATH must point to a readable file when DISPATCH_INPUT_MODE=analyst"
                )
        if cls.FEEDBACK_ENABLED:
            if not cls.DOCUMENT_LINK_SECRET:
                raise ValueError(
                    "DOCUMENT_LINK_SECRET is required when FEEDBACK_ENABLED=true"
                )
            if not _is_https_url(cls.DOCUMENT_VIEWER_URL):
                raise ValueError(
                    "DOCUMENT_VIEWER_URL must be a valid HTTPS URL when FEEDBACK_ENABLED=true"
                )
