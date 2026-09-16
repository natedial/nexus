"""Configuration management using pydantic-settings."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "RESEARCH_PARSER_"

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


def _env(name: str) -> AliasChoices:
    """Accept the prefixed name, then the pre-monorepo unprefixed name."""
    return AliasChoices(f"{ENV_PREFIX}{name}".lower(), name.lower())


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        # Root shared values first, package overrides second.
        env_file=(REPO_ROOT / ".env", PACKAGE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Shared across the pipeline: unprefixed, set at the repo root.
    google_credentials_path: Path = Field(
        default=Path("/app/credentials/service-account.json"),
        description="Path to Google service account JSON file",
    )
    google_drive_folder_id: str = Field(
        ...,
        description="Google Drive folder ID to watch for new PDFs",
    )
    supabase_url: str = Field(
        ...,
        description="Supabase project URL",
    )
    supabase_key: str = Field(
        ...,
        description="Supabase anon or service role key",
    )

    # Parser-owned: RESEARCH_PARSER_* in packages/research_parser/.env.
    poll_interval_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        validation_alias=_env("POLL_INTERVAL_MINUTES"),
        description="How often to poll Google Drive for new files",
    )
    catchup_days: int = Field(
        default=0,
        ge=0,
        validation_alias=_env("CATCHUP_DAYS"),
        description="Process files from the last N days on startup before scheduling",
    )
    drive_since_date: str | None = Field(
        default=None,
        validation_alias=_env("DRIVE_SINCE_DATE"),
        description="Only consider files created on/after this date (YYYY-MM-DD, UTC)",
    )

    # Local state
    state_db_path: Path = Field(
        default=Path("data/state.db"),
        validation_alias=_env("STATE_DB_PATH"),
        description="Path to SQLite state database",
    )
    artifact_base_dir: Path = Field(
        default=Path("data/artifacts"),
        validation_alias=_env("ARTIFACT_BASE_DIR"),
        description="Base directory for per-document artifact output",
    )

    # Optional local MinerU fallback
    mineru_enabled: bool = Field(
        default=False,
        validation_alias=_env("MINERU_ENABLED"),
        description="Enable MinerU as a local parser fallback after Docling",
    )
    mineru_bin_path: Path | None = Field(
        default=None,
        validation_alias=_env("MINERU_BIN_PATH"),
        description="Path to the MinerU CLI executable when MinerU fallback is enabled",
    )
    mineru_backend: str = Field(
        default="pipeline",
        validation_alias=_env("MINERU_BACKEND"),
        description="MinerU backend to invoke via CLI",
    )
    mineru_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        validation_alias=_env("MINERU_TIMEOUT_SECONDS"),
        description="Timeout for a single MinerU CLI parse",
    )
    docling_ocr_retry: bool = Field(
        default=True,
        validation_alias=_env("DOCLING_OCR_RETRY"),
        description="Retry Docling with OCR when the digital parse looks thin or gappy",
    )

    # Retry settings
    max_retries: int = Field(
        default=3,
        validation_alias=_env("MAX_RETRIES"),
        description="Max retries for API calls",
    )
    retry_delay_seconds: int = Field(
        default=5,
        validation_alias=_env("RETRY_DELAY_SECONDS"),
        description="Initial retry delay",
    )
    stale_processing_timeout_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        validation_alias=_env("STALE_PROCESSING_TIMEOUT_MINUTES"),
        description="Mark in-progress files stale after this many minutes and retry",
    )


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
