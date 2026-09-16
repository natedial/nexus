"""Configuration management using pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "MORNING_RESEARCH_"

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _PACKAGE_ROOT.parents[1]

_DEFAULT_STATE_PATH = Path(
    "/Users/ncdial/devwork/local_codex/state/research_digest_state.json"
)


def _env(name: str) -> AliasChoices:
    """Accept the prefixed name, then the pre-monorepo unprefixed name."""
    return AliasChoices(f"{ENV_PREFIX}{name}".lower(), name.lower())


class Settings(BaseSettings):
    """Application settings loaded from environment variables (and `.env`).

    Shared credentials (Google Drive, Notion, Supabase) keep their unprefixed
    names and come from the repo-root `.env`. Settings owned by this package are
    `MORNING_RESEARCH_*` and come from this package's `.env`, which wins on
    conflicts.
    """

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _PACKAGE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    google_credentials_path: Path = Field(
        default=Path("/Users/ncdial/devwork/local_codex/credentials/service-account.json"),
    )
    google_drive_folder_id: str = Field(default="")

    notion_token: str = Field(default="")
    notion_database_id: str = Field(default="")
    notion_area_page_id: str = Field(
        default="",
        description="Notion page ID for Area=Job when Area is a relation property",
    )

    supabase_url: str | None = Field(default=None)
    supabase_key: str | None = Field(default=None)

    morning_research_state_path: Path = Field(default=_DEFAULT_STATE_PATH)
    morning_research_work_dir: Path = Field(default=Path("./work"))

    codex_bin: str = Field(default="codex", validation_alias=_env("CODEX_BIN"))
    codex_timeout_seconds: int = Field(
        default=3600, ge=1, validation_alias=_env("CODEX_TIMEOUT_SECONDS")
    )
    codex_model: str | None = Field(
        default=None, validation_alias=_env("CODEX_MODEL")
    )

    min_pdf_bytes: int = Field(
        default=2048, ge=0, validation_alias=_env("MIN_PDF_BYTES")
    )
    dry_run: bool = Field(default=False, validation_alias=_env("DRY_RUN"))

    @property
    def package_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def prompt_path(self) -> Path:
        return self.package_root / "prompts" / "daily_run.md"

    @property
    def agents_path(self) -> Path:
        return self.package_root / "AGENTS.md"

    def resolved_state_path(self) -> Path:
        path = self.morning_research_state_path
        return path if path.is_absolute() else (self.package_root / path).resolve()

    def resolved_work_dir(self) -> Path:
        path = self.morning_research_work_dir
        return path if path.is_absolute() else (self.package_root / path).resolve()

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def supabase_configured(self) -> bool:
        return self.supabase_enabled


def get_settings() -> Settings:
    return Settings()
