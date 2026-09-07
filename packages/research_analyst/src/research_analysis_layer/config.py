"""Environment-backed configuration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
import sqlite3

_API_LLM_PROVIDERS = {"openai", "openai_compatible"}
_CLI_LLM_PROVIDERS = {"codex"}
_SUPPORTED_LLM_PROVIDERS = _API_LLM_PROVIDERS | _CLI_LLM_PROVIDERS
_DEFAULT_CODEX_BINARIES = (
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _path_has_processed_files(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'processed_files'
                """
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return row is not None


def resolve_codex_bin(explicit: str | None = None) -> str | None:
    """Return an executable Codex CLI path, or None if it cannot be found."""
    if explicit and explicit.strip():
        path = Path(explicit.strip())
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        return None
    candidates: list[str] = []
    found = shutil.which("codex")
    if found:
        candidates.append(found)
    candidates.extend(_DEFAULT_CODEX_BINARIES)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def _resolve_state_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if _path_has_processed_files(path):
        return path.resolve()
    if path.is_absolute():
        return path

    repo_root = Path(__file__).resolve().parents[2]

    candidates = [
        Path.cwd() / path,
        Path.cwd().parent / "research_parser" / path,
        repo_root / path,
        repo_root.parent / "research_parser" / path,
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if _path_has_processed_files(resolved):
            return resolved
    if path.exists():
        return path.resolve()
    return path.resolve()


@dataclass(slots=True)
class Settings:
    """Bootstrap service settings."""

    analysis_db_url: str
    parsed_db_url: str
    parsed_db_key: str
    calendar_db_url: str
    calendar_db_key: str
    calendar_match_source: str
    calendar_source_name: str
    state_db_path: Path
    batch_size: int
    cron_mode_enabled: bool
    analysis_version: str
    chunker_version: str
    assertion_extractor_version: str
    resolver_version: str
    request_timeout_seconds: int
    min_full_text_chars: int
    min_quality_score: float
    min_usable_theme_ratio: float
    backfill_require_warning_free: bool
    agent_execution_enabled: bool = False
    agent_llm_provider: str | None = None
    agent_llm_api_key: str | None = None
    agent_llm_base_url: str | None = None
    agent_llm_codex_bin: str | None = None
    agent_llm_codex_model: str | None = None
    agent_llm_timeout_seconds: int | None = None
    agent_llm_max_output_tokens: int = 16384
    agent_llm_reasoning_effort: str | None = None
    analyst_round_mode: str = "rounds"
    analyst_tools_enabled: bool = False
    distill_tool_module: str = "distill_tool.api"
    analyst_batch_out_dir: Path = Path("/var/research/analyst")
    tholos_enabled: bool = False
    tholos_base_url: str = "http://localhost:8004"
    tholos_timeout_seconds: int = 30
    eval_capture_enabled: bool = False
    eval_captures_dir: Path = Path("evals/captures")
    analyst_debate_mode: str = "off"
    analyst_debate_judge_model: str | None = None
    analyst_max_debate_arguments: int = 8
    referent_granularity: str = "coarse"

    @classmethod
    def from_env(cls) -> "Settings":
        parsed_db_url = os.getenv("PARSED_DB_URL") or os.getenv("SUPABASE_URL", "")
        parsed_db_key = os.getenv("PARSED_DB_KEY") or os.getenv("SUPABASE_KEY", "")
        calendar_match_source = os.getenv("CALENDAR_MATCH_SOURCE", "economic_events")
        calendar_db_url = os.getenv("CALENDAR_DB_URL") or parsed_db_url
        calendar_db_key = os.getenv("CALENDAR_DB_KEY") or parsed_db_key
        agent_llm_provider = os.getenv("AGENT_LLM_PROVIDER")
        agent_llm_api_key = os.getenv("AGENT_LLM_API_KEY")
        provider_name = (agent_llm_provider or "").strip().lower()
        agent_execution_enabled = _env_bool(
            "AGENT_EXECUTION_ENABLED",
            bool(agent_llm_api_key) or provider_name in _CLI_LLM_PROVIDERS,
        )
        default_calendar_source_name = (
            "scrivener"
            if calendar_match_source == "release_dates"
            else "economic_events"
        )
        return cls(
            analysis_db_url=os.getenv("ANALYSIS_DB_URL", "sqlite:///data/analysis.db"),
            parsed_db_url=parsed_db_url,
            parsed_db_key=parsed_db_key,
            calendar_db_url=calendar_db_url,
            calendar_db_key=calendar_db_key,
            calendar_match_source=calendar_match_source,
            calendar_source_name=os.getenv(
                "CALENDAR_SOURCE_NAME",
                default_calendar_source_name,
            ),
            state_db_path=_resolve_state_db_path(
                os.getenv("STATE_DB_PATH", "../research_parser/data/state.db")
            ),
            batch_size=_env_int("BATCH_SIZE", 25),
            cron_mode_enabled=_env_bool("CRON_MODE_ENABLED", True),
            analysis_version=os.getenv("ANALYSIS_VERSION", "argmap-v1"),
            chunker_version=os.getenv("CHUNKER_VERSION", "deterministic-theme-v1"),
            assertion_extractor_version=os.getenv(
                "ASSERTION_EXTRACTOR_VERSION",
                "deterministic-theme-v1",
            ),
            resolver_version=os.getenv("RESOLVER_VERSION", "bootstrap-v1"),
            request_timeout_seconds=_env_int("REQUEST_TIMEOUT_SECONDS", 30),
            min_full_text_chars=_env_int("MIN_FULL_TEXT_CHARS", 500),
            min_quality_score=_env_float("MIN_QUALITY_SCORE", 0.6),
            min_usable_theme_ratio=_env_float("MIN_USABLE_THEME_RATIO", 0.6),
            backfill_require_warning_free=_env_bool(
                "BACKFILL_REQUIRE_WARNING_FREE",
                True,
            ),
            agent_execution_enabled=agent_execution_enabled,
            agent_llm_provider=agent_llm_provider,
            agent_llm_api_key=agent_llm_api_key,
            agent_llm_base_url=os.getenv("AGENT_LLM_BASE_URL"),
            agent_llm_codex_bin=os.getenv("AGENT_LLM_CODEX_BIN") or None,
            agent_llm_codex_model=os.getenv("AGENT_LLM_CODEX_MODEL") or None,
            agent_llm_timeout_seconds=(
                _env_int("AGENT_LLM_TIMEOUT_SECONDS", 60)
                if os.getenv("AGENT_LLM_TIMEOUT_SECONDS") is not None
                else None
            ),
            agent_llm_max_output_tokens=_env_int(
                "AGENT_LLM_MAX_OUTPUT_TOKENS", 16384
            ),
            agent_llm_reasoning_effort=os.getenv("AGENT_LLM_REASONING_EFFORT")
            or None,
            analyst_round_mode=os.getenv("ANALYST_ROUND_MODE", "rounds"),
            analyst_tools_enabled=_env_bool("ANALYST_TOOLS_ENABLED", False),
            distill_tool_module=os.getenv("DISTILL_TOOL_MODULE", "distill_tool.api"),
            analyst_batch_out_dir=Path(
                os.getenv("ANALYST_BATCH_OUT_DIR", "/var/research/analyst")
            ),
            tholos_enabled=_env_bool("THOLOS_ENABLED", False),
            tholos_base_url=os.getenv("THOLOS_BASE_URL", "http://localhost:8004"),
            tholos_timeout_seconds=_env_int("THOLOS_TIMEOUT_SECONDS", 30),
            eval_capture_enabled=_env_bool("EVAL_CAPTURE_ENABLED", False),
            eval_captures_dir=Path(os.getenv("EVAL_CAPTURES_DIR", "evals/captures")),
            analyst_debate_mode=os.getenv("ANALYST_DEBATE_MODE", "off"),
            analyst_debate_judge_model=os.getenv("ANALYST_DEBATE_JUDGE_MODEL"),
            analyst_max_debate_arguments=_env_int("ANALYST_MAX_DEBATE_ARGUMENTS", 8),
            referent_granularity=os.getenv("REFERENT_GRANULARITY", "coarse"),
        )

    @property
    def analysis_db_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.analysis_db_url.startswith(prefix):
            raise ValueError(
                "Bootstrap analysis store only supports sqlite URLs, "
                f"received {self.analysis_db_url!r}"
            )
        return Path(self.analysis_db_url[len(prefix) :])

    def validate(self) -> list[str]:
        """Return human-readable configuration errors."""
        errors: list[str] = []
        if not self.state_db_path.exists():
            errors.append(f"state db not found: {self.state_db_path}")
        elif not _path_has_processed_files(self.state_db_path):
            errors.append(
                f"state db missing processed_files table: {self.state_db_path}"
            )
        if not self.parsed_db_url:
            errors.append("missing parsed db url: set PARSED_DB_URL or SUPABASE_URL")
        if not self.parsed_db_key:
            errors.append("missing parsed db key: set PARSED_DB_KEY or SUPABASE_KEY")
        if not self.calendar_db_url:
            errors.append("missing calendar db url: set CALENDAR_DB_URL")
        if not self.calendar_db_key:
            errors.append("missing calendar db key: set CALENDAR_DB_KEY")
        if self.calendar_match_source not in {"economic_events", "release_dates"}:
            errors.append(
                "invalid calendar match source: expected economic_events or release_dates, "
                f"received {self.calendar_match_source!r}"
            )
        if self.agent_execution_enabled:
            provider = (self.agent_llm_provider or "").strip().lower()
            if not provider:
                errors.append("missing agent llm provider: set AGENT_LLM_PROVIDER")
            elif provider == "anthropic":
                errors.append(
                    "anthropic is no longer supported: set AGENT_LLM_PROVIDER "
                    "to openai, openai_compatible, or codex"
                )
            elif provider not in _SUPPORTED_LLM_PROVIDERS:
                errors.append(
                    "invalid agent llm provider: expected openai, "
                    "openai_compatible, or codex, "
                    f"received {self.agent_llm_provider!r}"
                )
            if provider in _API_LLM_PROVIDERS and not self.agent_llm_api_key:
                errors.append("missing agent llm api key: set AGENT_LLM_API_KEY")
            if provider in _CLI_LLM_PROVIDERS:
                binary = resolve_codex_bin(self.agent_llm_codex_bin)
                if not binary:
                    errors.append(
                        "codex CLI not found: install `codex` or set AGENT_LLM_CODEX_BIN"
                    )
        if self.agent_llm_max_output_tokens <= 0:
            errors.append(
                "invalid agent llm max output tokens: must be positive, "
                f"received {self.agent_llm_max_output_tokens}"
            )
        if self.analyst_debate_mode not in {"off", "shadow", "on"}:
            errors.append(
                "invalid analyst_debate_mode: expected off, shadow, or on, "
                f"received {self.analyst_debate_mode!r}"
            )
        if self.analyst_max_debate_arguments <= 0:
            errors.append(
                "invalid analyst_max_debate_arguments: must be positive, "
                f"received {self.analyst_max_debate_arguments}"
            )
        if self.referent_granularity not in {"coarse", "fine"}:
            errors.append(
                "invalid referent_granularity: expected coarse or fine, "
                f"received {self.referent_granularity!r}"
            )
        return errors
