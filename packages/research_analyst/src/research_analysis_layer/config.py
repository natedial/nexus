"""Environment-backed configuration."""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from research_analysis_layer.env import ENV_PREFIX, env

_API_LLM_PROVIDERS = {"openai", "openai_compatible"}
_CLI_LLM_PROVIDERS = {"codex"}
_SUPPORTED_LLM_PROVIDERS = _API_LLM_PROVIDERS | _CLI_LLM_PROVIDERS
_DEFAULT_CODEX_BINARIES = (
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
)


def _env_bool(
    name: str, default: bool, *, legacy: str | Sequence[str] | None = None
) -> bool:
    value = env(name, legacy=legacy)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(
    name: str, default: int, *, legacy: str | Sequence[str] | None = None
) -> int:
    value = env(name, legacy=legacy)
    if value is None:
        return default
    return int(value)


def _env_float(
    name: str, default: float, *, legacy: str | Sequence[str] | None = None
) -> float:
    value = env(name, legacy=legacy)
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
    parsed_database_url: str | None
    calendar_db_url: str
    calendar_db_key: str
    calendar_database_url: str | None
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
    consensus_min_publishers: int = 2
    consensus_shift_diversity_threshold: int = 3
    digest_consensus_mode: str = "off"
    argument_judge_weight_rationale_fidelity: float = 0.25
    argument_judge_weight_substantive: float = 0.25
    argument_judge_weight_groundedness: float = 0.25
    argument_judge_weight_phantom: float = 0.25
    promotion_gate_mode: str = "advisory"
    promotion_gate_baseline_path: Path = Path("evals/baselines/rubric_rates.json")
    promotion_gate_floor_claim_rationale: float = 0.0
    promotion_gate_floor_claim_evidenced: float = 0.0
    promotion_gate_floor_divergence_grounded: float = 0.0
    promotion_gate_floor_divergence_attributed: float = 0.0
    promotion_gate_floor_consensus_multi_source: float = 0.0

    @classmethod
    def from_env(cls) -> "Settings":
        # The parsed and calendar stores default to the pipeline-wide Supabase
        # project configured in the repo-root .env.
        nexus_database_url = env("DATABASE_URL") or os.getenv("NEXUS_DATABASE_URL")
        parsed_database_url = env("PARSED_DATABASE_URL") or nexus_database_url
        calendar_database_url = env("CALENDAR_DATABASE_URL") or parsed_database_url
        parsed_db_url = env("PARSED_DB_URL") or os.getenv("SUPABASE_URL", "")
        parsed_db_key = env("PARSED_DB_KEY") or os.getenv("SUPABASE_KEY", "")
        calendar_match_source = env("CALENDAR_MATCH_SOURCE", "economic_events")
        calendar_db_url = env("CALENDAR_DB_URL") or parsed_db_url
        calendar_db_key = env("CALENDAR_DB_KEY") or parsed_db_key
        analysis_db_url = env("ANALYSIS_DB_URL", "sqlite:///data/analysis.db")
        if nexus_database_url and analysis_db_url.startswith("sqlite://"):
            analysis_db_url = nexus_database_url
        agent_llm_provider = env("AGENT_LLM_PROVIDER")
        agent_llm_api_key = env("AGENT_LLM_API_KEY")
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
            analysis_db_url=analysis_db_url,
            parsed_db_url=parsed_db_url,
            parsed_db_key=parsed_db_key,
            parsed_database_url=parsed_database_url,
            calendar_db_url=calendar_db_url,
            calendar_db_key=calendar_db_key,
            calendar_database_url=calendar_database_url,
            calendar_match_source=calendar_match_source,
            calendar_source_name=env(
                "CALENDAR_SOURCE_NAME",
                default_calendar_source_name,
            ),
            # Upstream artifact: falls back to the parser's own setting.
            state_db_path=_resolve_state_db_path(
                env(
                    "STATE_DB_PATH",
                    "../research_parser/data/state.db",
                    legacy=("RESEARCH_PARSER_STATE_DB_PATH", "STATE_DB_PATH"),
                )
            ),
            batch_size=_env_int("BATCH_SIZE", 25),
            cron_mode_enabled=_env_bool("CRON_MODE_ENABLED", True),
            analysis_version=env("ANALYSIS_VERSION", "argmap-v1"),
            chunker_version=env("CHUNKER_VERSION", "deterministic-theme-v1"),
            assertion_extractor_version=env(
                "ASSERTION_EXTRACTOR_VERSION",
                "deterministic-theme-v1",
            ),
            resolver_version=env("RESOLVER_VERSION", "bootstrap-v1"),
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
            agent_llm_base_url=env("AGENT_LLM_BASE_URL"),
            agent_llm_codex_bin=env("AGENT_LLM_CODEX_BIN") or None,
            agent_llm_codex_model=env("AGENT_LLM_CODEX_MODEL") or None,
            agent_llm_timeout_seconds=(
                _env_int("AGENT_LLM_TIMEOUT_SECONDS", 60)
                if env("AGENT_LLM_TIMEOUT_SECONDS") is not None
                else None
            ),
            agent_llm_max_output_tokens=_env_int(
                "AGENT_LLM_MAX_OUTPUT_TOKENS", 16384
            ),
            agent_llm_reasoning_effort=env("AGENT_LLM_REASONING_EFFORT") or None,
            analyst_round_mode=env(
                "ROUND_MODE", "rounds", legacy="ANALYST_ROUND_MODE"
            ),
            analyst_tools_enabled=_env_bool(
                "TOOLS_ENABLED", False, legacy="ANALYST_TOOLS_ENABLED"
            ),
            distill_tool_module=env("DISTILL_TOOL_MODULE", "distill_tool.api"),
            analyst_batch_out_dir=Path(
                env(
                    "BATCH_OUT_DIR",
                    "/var/research/analyst",
                    legacy="ANALYST_BATCH_OUT_DIR",
                )
            ),
            tholos_enabled=_env_bool("THOLOS_ENABLED", False),
            tholos_base_url=env("THOLOS_BASE_URL", "http://localhost:8004"),
            tholos_timeout_seconds=_env_int("THOLOS_TIMEOUT_SECONDS", 30),
            eval_capture_enabled=_env_bool("EVAL_CAPTURE_ENABLED", False),
            eval_captures_dir=Path(env("EVAL_CAPTURES_DIR", "evals/captures")),
            analyst_debate_mode=env(
                "DEBATE_MODE", "off", legacy="ANALYST_DEBATE_MODE"
            ),
            analyst_debate_judge_model=env(
                "DEBATE_JUDGE_MODEL", legacy="ANALYST_DEBATE_JUDGE_MODEL"
            ),
            analyst_max_debate_arguments=_env_int(
                "MAX_DEBATE_ARGUMENTS", 8, legacy="ANALYST_MAX_DEBATE_ARGUMENTS"
            ),
            referent_granularity=env("REFERENT_GRANULARITY", "coarse"),
            consensus_min_publishers=_env_int("CONSENSUS_MIN_PUBLISHERS", 2),
            consensus_shift_diversity_threshold=_env_int(
                "CONSENSUS_SHIFT_DIVERSITY_THRESHOLD", 3
            ),
            digest_consensus_mode=env("DIGEST_CONSENSUS_MODE", "off"),
            argument_judge_weight_rationale_fidelity=_env_float(
                "ARGUMENT_JUDGE_WEIGHT_RATIONALE_FIDELITY", 0.25
            ),
            argument_judge_weight_substantive=_env_float(
                "ARGUMENT_JUDGE_WEIGHT_SUBSTANTIVE", 0.25
            ),
            argument_judge_weight_groundedness=_env_float(
                "ARGUMENT_JUDGE_WEIGHT_GROUNDEDNESS", 0.25
            ),
            argument_judge_weight_phantom=_env_float(
                "ARGUMENT_JUDGE_WEIGHT_PHANTOM", 0.25
            ),
            promotion_gate_mode=env("PROMOTION_GATE_MODE", "advisory"),
            promotion_gate_baseline_path=Path(
                env(
                    "PROMOTION_GATE_BASELINE_PATH",
                    "evals/baselines/rubric_rates.json",
                )
            ),
            promotion_gate_floor_claim_rationale=_env_float(
                "PROMOTION_GATE_FLOOR_CLAIM_RATIONALE", 0.0
            ),
            promotion_gate_floor_claim_evidenced=_env_float(
                "PROMOTION_GATE_FLOOR_CLAIM_EVIDENCED", 0.0
            ),
            promotion_gate_floor_divergence_grounded=_env_float(
                "PROMOTION_GATE_FLOOR_DIVERGENCE_GROUNDED", 0.0
            ),
            promotion_gate_floor_divergence_attributed=_env_float(
                "PROMOTION_GATE_FLOOR_DIVERGENCE_ATTRIBUTED", 0.0
            ),
            promotion_gate_floor_consensus_multi_source=_env_float(
                "PROMOTION_GATE_FLOOR_CONSENSUS_MULTI_SOURCE", 0.0
            ),
        )

    @property
    def analysis_database_url(self) -> str | None:
        if self.analysis_db_url.startswith("postgresql"):
            return self.analysis_db_url
        return None

    @property
    def analysis_db_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.analysis_db_url.startswith(prefix):
            raise ValueError(
                "analysis_db_path requires a sqlite URL; "
                f"received {self.analysis_db_url!r}"
            )
        return Path(self.analysis_db_url[len(prefix) :])

    @property
    def uses_postgres(self) -> bool:
        return self.analysis_database_url is not None

    def validate(self) -> list[str]:
        """Return human-readable configuration errors."""
        errors: list[str] = []
        if not self.state_db_path.exists():
            errors.append(f"state db not found: {self.state_db_path}")
        elif not _path_has_processed_files(self.state_db_path):
            errors.append(
                f"state db missing processed_files table: {self.state_db_path}"
            )
        postgres_reads = bool(
            (self.parsed_database_url and self.parsed_database_url.startswith("postgresql"))
            or (self.calendar_database_url and self.calendar_database_url.startswith("postgresql"))
        )
        if not postgres_reads:
            if not self.parsed_db_url:
                errors.append(
                    "missing parsed db url: set "
                    f"{ENV_PREFIX}PARSED_DB_URL, {ENV_PREFIX}PARSED_DATABASE_URL, "
                    "or NEXUS_DATABASE_URL"
                )
            if not self.parsed_db_key:
                errors.append(
                    "missing parsed db key: set "
                    f"{ENV_PREFIX}PARSED_DB_KEY or SUPABASE_KEY"
                )
            if not self.calendar_db_url:
                errors.append(
                    f"missing calendar db url: set {ENV_PREFIX}CALENDAR_DB_URL"
                )
            if not self.calendar_db_key:
                errors.append(
                    f"missing calendar db key: set {ENV_PREFIX}CALENDAR_DB_KEY"
                )
        if self.calendar_match_source not in {"economic_events", "release_dates"}:
            errors.append(
                "invalid calendar match source: expected economic_events or release_dates, "
                f"received {self.calendar_match_source!r}"
            )
        if self.agent_execution_enabled:
            provider = (self.agent_llm_provider or "").strip().lower()
            if not provider:
                errors.append(
                    f"missing agent llm provider: set {ENV_PREFIX}AGENT_LLM_PROVIDER"
                )
            elif provider == "anthropic":
                errors.append(
                    f"anthropic is no longer supported: set {ENV_PREFIX}AGENT_LLM_PROVIDER "
                    "to openai, openai_compatible, or codex"
                )
            elif provider not in _SUPPORTED_LLM_PROVIDERS:
                errors.append(
                    "invalid agent llm provider: expected openai, "
                    "openai_compatible, or codex, "
                    f"received {self.agent_llm_provider!r}"
                )
            if provider in _API_LLM_PROVIDERS and not self.agent_llm_api_key:
                errors.append(
                    f"missing agent llm api key: set {ENV_PREFIX}AGENT_LLM_API_KEY"
                )
            if provider in _CLI_LLM_PROVIDERS:
                binary = resolve_codex_bin(self.agent_llm_codex_bin)
                if not binary:
                    errors.append(
                        "codex CLI not found: install `codex` or set "
                        f"{ENV_PREFIX}AGENT_LLM_CODEX_BIN"
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
        if self.consensus_min_publishers < 2:
            errors.append(
                "invalid consensus_min_publishers: must be >= 2, "
                f"received {self.consensus_min_publishers}"
            )
        if self.consensus_shift_diversity_threshold < 2:
            errors.append(
                "invalid consensus_shift_diversity_threshold: must be >= 2, "
                f"received {self.consensus_shift_diversity_threshold}"
            )
        if self.digest_consensus_mode not in {"off", "shadow", "on"}:
            errors.append(
                "invalid digest_consensus_mode: expected off, shadow, or on, "
                f"received {self.digest_consensus_mode!r}"
            )
        if self.promotion_gate_mode not in {"advisory", "blocking"}:
            errors.append(
                "invalid promotion_gate_mode: expected advisory or blocking, "
                f"received {self.promotion_gate_mode!r}"
            )
        for label, value in (
            (
                "promotion_gate_floor_claim_rationale",
                self.promotion_gate_floor_claim_rationale,
            ),
            (
                "promotion_gate_floor_claim_evidenced",
                self.promotion_gate_floor_claim_evidenced,
            ),
            (
                "promotion_gate_floor_divergence_grounded",
                self.promotion_gate_floor_divergence_grounded,
            ),
            (
                "promotion_gate_floor_divergence_attributed",
                self.promotion_gate_floor_divergence_attributed,
            ),
            (
                "promotion_gate_floor_consensus_multi_source",
                self.promotion_gate_floor_consensus_multi_source,
            ),
        ):
            if value < 0 or value > 1:
                errors.append(
                    f"invalid {label}: must be between 0 and 1, received {value}"
                )
        for label, value in (
            (
                "argument_judge_weight_rationale_fidelity",
                self.argument_judge_weight_rationale_fidelity,
            ),
            (
                "argument_judge_weight_substantive",
                self.argument_judge_weight_substantive,
            ),
            (
                "argument_judge_weight_groundedness",
                self.argument_judge_weight_groundedness,
            ),
            (
                "argument_judge_weight_phantom",
                self.argument_judge_weight_phantom,
            ),
        ):
            if value < 0:
                errors.append(f"invalid {label}: must be >= 0, received {value}")
        return errors

    @property
    def argument_judge_weights(self) -> dict[str, float]:
        """Rubric weights for `ArgumentJudge`. Not pass/fail cutoffs."""
        return {
            "rationale_fidelity": self.argument_judge_weight_rationale_fidelity,
            "substantive_vs_framing": self.argument_judge_weight_substantive,
            "groundedness": self.argument_judge_weight_groundedness,
            "phantom_counterparty": self.argument_judge_weight_phantom,
        }

    @property
    def promotion_gate_floors(self) -> dict[str, float]:
        """Absolute rate floors for `shadow → on`. Defaults are 0.0 (advisory)."""
        return {
            "claim_rationale_rate": self.promotion_gate_floor_claim_rationale,
            "claim_evidenced_rate": self.promotion_gate_floor_claim_evidenced,
            "divergence_grounded_rate": self.promotion_gate_floor_divergence_grounded,
            "divergence_attributed_rate": self.promotion_gate_floor_divergence_attributed,
            "consensus_multi_source_rate": (
                self.promotion_gate_floor_consensus_multi_source
            ),
        }

    def resolve_promotion_gate_baseline_path(self) -> Path:
        path = Path(self.promotion_gate_baseline_path)
        if path.is_absolute():
            return path
        package_root = Path(__file__).resolve().parents[2]
        return (package_root / path).resolve()
