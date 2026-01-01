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

    # LLM API Keys
    anthropic_api_key: str = Field(
        ...,
        description="Anthropic API key for Claude models",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key (optional, for OpenAI models)",
    )

    # LlamaIndex Cloud
    llamaindex_api_key: str = Field(
        ...,
        description="LlamaIndex Cloud API key for PDF parsing",
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

    # Local state
    state_db_path: Path = Field(
        default=Path("/app/data/state.db"),
        description="Path to SQLite state database",
    )

    # Retry settings
    max_retries: int = Field(default=3, description="Max retries for API calls")
    retry_delay_seconds: int = Field(default=5, description="Initial retry delay")

    # Model config path (optional override)
    model_config_path: Path | None = Field(
        default=None,
        description="Path to models.yaml config file (defaults to config/models.yaml)",
    )


def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
