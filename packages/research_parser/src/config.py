"""Configuration management using pydantic-settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Google Drive
    google_credentials_path: Path = Field(
        default=Path("/app/credentials/service-account.json"),
        description="Path to Google service account JSON file",
    )
    google_drive_folder_id: str = Field(
        ...,
        description="Google Drive folder ID to watch for new PDFs",
    )

    # Supabase
    supabase_url: str = Field(
        ...,
        description="Supabase project URL",
    )
    supabase_key: str = Field(
        ...,
        description="Supabase anon or service role key",
    )

    # Processing settings
    poll_interval_minutes: int = Field(
        default=5,
        ge=1,
        le=60,
        description="How often to poll Google Drive for new files",
    )
    catchup_days: int = Field(
        default=0,
        ge=0,
        description="Process files from the last N days on startup before scheduling",
    )
    drive_since_date: str | None = Field(
        default=None,
        description="Only consider files created on/after this date (YYYY-MM-DD, UTC)",
    )

    # Local state
    state_db_path: Path = Field(
        default=Path("data/state.db"),
        description="Path to SQLite state database",
    )
    artifact_base_dir: Path = Field(
        default=Path("data/artifacts"),
        description="Base directory for per-document artifact output",
    )

    # Optional local MinerU fallback
    mineru_enabled: bool = Field(
        default=False,
        description="Enable MinerU as a local parser fallback after Docling",
    )
    mineru_bin_path: Path | None = Field(
        default=None,
        description="Path to the MinerU CLI executable when MinerU fallback is enabled",
    )
    mineru_backend: str = Field(
        default="pipeline",
        description="MinerU backend to invoke via CLI",
    )
    mineru_timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Timeout for a single MinerU CLI parse",
    )
    docling_ocr_retry: bool = Field(
        default=True,
        description="Retry Docling with OCR when the digital parse looks thin or gappy",
    )

    # Retry settings
    max_retries: int = Field(default=3, description="Max retries for API calls")
    retry_delay_seconds: int = Field(default=5, description="Initial retry delay")
    stale_processing_timeout_minutes: int = Field(
        default=30,
        ge=5,
        le=1440,
        description="Mark in-progress files stale after this many minutes and retry",
    )


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
