import os
from pathlib import Path
from dotenv import load_dotenv

ENV_PREFIX = "RESEARCH_DISPATCHER_"

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]

# Shared credentials from the repo root first, dispatcher settings on top.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(PACKAGE_ROOT / ".env", override=True)

VALID_TRADE_CONVICTION_FILTERS = {"high", "medium", "all"}
VALID_DISPATCH_INPUT_MODES = {"analyst"}


def _from_env(name: str, default: str | None = None, *, legacy: str | None = None):
    """Read `RESEARCH_DISPATCHER_<name>`, then the deprecated unprefixed name.

    `legacy` overrides the fallback name for variables whose unprefixed spelling
    already carried a package word, such as `MODE` -> `RESEARCH_DISPATCHER_MODE`.
    """
    for candidate in (f"{ENV_PREFIX}{name}", legacy or name):
        raw = os.getenv(candidate)
        if raw is not None:
            return raw
    return default


def _int_from_env(name: str, default: int) -> int:
    """Parse int env var, falling back to default on empty/invalid values."""
    raw = _from_env(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_from_env(name: str, default: bool) -> bool:
    """Parse boolean env var, falling back to default on empty values."""
    raw = _from_env(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes")


def parse_trade_conviction_filter(raw: str | None, default: str = "high") -> str:
    """Normalize the trade conviction filter and fail fast on invalid values."""
    candidate = (raw or "").strip().lower()
    if not candidate:
        return default
    if candidate == "low":
        return "all"
    if candidate in VALID_TRADE_CONVICTION_FILTERS:
        return candidate
    raise ValueError(
        f"{ENV_PREFIX}FILTER_TRADE_CONVICTION must be one of: high, medium, all"
    )


def parse_dispatch_input_mode(raw: str | None, default: str = "analyst") -> str:
    """Normalize dispatcher input mode and fail fast on invalid values."""
    candidate = (raw or "").strip().lower()
    if not candidate:
        return default
    if candidate == "parser":
        raise ValueError(
            f"{ENV_PREFIX}INPUT_MODE=parser is no longer supported; use analyst"
        )
    if candidate in VALID_DISPATCH_INPUT_MODES:
        return candidate
    raise ValueError(f"{ENV_PREFIX}INPUT_MODE must be analyst")


class Config:
    """Application configuration loaded from environment variables.

    Shared credentials keep their unprefixed names and come from the repo-root
    `.env`. Dispatcher-owned settings are `RESEARCH_DISPATCHER_*` and come from
    this package's `.env`; the unprefixed spellings still work as a deprecated
    fallback.
    """

    # Local PostgreSQL (calendar reads; pipeline_ops lives in same instance)
    DATABASE_URL = _from_env("DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL")

    # LLM API keys (shared, account-scoped credentials)
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Optional
    DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY")  # Optional
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")  # Optional

    # Synthesis toggle
    ENABLE_SYNTHESIS = _from_env("ENABLE_SYNTHESIS", "true").lower() in (
        "true",
        "1",
        "yes",
    )

    # Skill-based pipeline (two-stage synthesis instead of monolithic prompt)
    USE_SKILL_PIPELINE = _from_env("USE_SKILL_PIPELINE", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    # Email
    SMTP_SERVER = _from_env("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(_from_env("SMTP_PORT", "587"))
    SMTP_USERNAME = _from_env("SMTP_USERNAME")
    SMTP_PASSWORD = _from_env("SMTP_PASSWORD")
    EMAIL_FROM = _from_env("EMAIL_FROM")
    EMAIL_TO = _from_env("EMAIL_TO")

    # Report
    REPORT_TITLE = _from_env("REPORT_TITLE", "Document Analysis Report")
    DISPATCH_INPUT_MODE = parse_dispatch_input_mode(
        _from_env("INPUT_MODE", legacy="DISPATCH_INPUT_MODE")
    )
    ANALYST_BATCH_PATH = _from_env("ANALYST_BATCH_PATH", "").strip()
    DISPATCH_DB_PATH = _from_env(
        "DB_PATH",
        os.path.join("state", "dispatch_history.db"),
        legacy="DISPATCH_DB_PATH",
    )

    # Mode: debug or production (dispatch ledger is the source of truth)
    MODE = _from_env("MODE", "debug").lower()

    # Filters
    DATE_RANGE_DAYS = _int_from_env("DATE_RANGE_DAYS", 3)  # Number of days to look back
    FILTER_SOURCES = _from_env(
        "FILTER_SOURCES", ""
    )  # Comma-separated list of sources (empty = all)
    FILTER_REGION = _from_env(
        "FILTER_REGION", ""
    )  # Filter by region: US, EU, UK, Japan, China, EM, Global (empty = all)
    FILTER_ASSET_FOCUS = _from_env(
        "FILTER_ASSET_FOCUS", ""
    )  # Filter by asset: rates, credit, FX, equities, commodities, multi-asset (empty = all)
    FILTER_TRADE_CONVICTION = parse_trade_conviction_filter(
        _from_env("FILTER_TRADE_CONVICTION", "high")
    )  # Filter trades: high, medium, all (default: high; low aliases to all)
    CALENDAR_COUNTRY = _from_env(
        "CALENDAR_COUNTRY", "US"
    )  # Country for calendar events

    @classmethod
    def validate(cls):
        """Validate that all required configuration is present."""
        required = [
            "DATABASE_URL",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "EMAIL_FROM",
            "EMAIL_TO",
        ]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        cls.DISPATCH_INPUT_MODE = parse_dispatch_input_mode(cls.DISPATCH_INPUT_MODE)
        if not cls.ANALYST_BATCH_PATH:
            raise ValueError("ANALYST_BATCH_PATH is required")
        if not os.path.isfile(cls.ANALYST_BATCH_PATH) or not os.access(
            cls.ANALYST_BATCH_PATH, os.R_OK
        ):
            raise ValueError("ANALYST_BATCH_PATH must point to a readable file")
