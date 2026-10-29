"""Shared ``Settings`` builder for unit tests.

``Settings`` has many required fields; keeping one baseline here means a new
required field only needs a dummy value in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_analysis_layer.config import Settings


def make_test_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "analysis_db_url": "sqlite:///data/analysis.db",
        "parsed_db_url": "https://example.supabase.co",
        "parsed_db_key": "secret",
        "parsed_database_url": "postgresql://example/parsed",
        "calendar_db_url": "https://calendar.example.supabase.co",
        "calendar_db_key": "calendar-secret",
        "calendar_database_url": "postgresql://example/calendar",
        "calendar_match_source": "economic_events",
        "calendar_source_name": "economic_events",
        "state_db_path": Path("data/state.db"),
        "batch_size": 25,
        "cron_mode_enabled": True,
        "analysis_version": "bootstrap-v1",
        "chunker_version": "deterministic-theme-v1",
        "assertion_extractor_version": "deterministic-theme-v1",
        "resolver_version": "bootstrap-v1",
        "request_timeout_seconds": 30,
        "min_full_text_chars": 500,
        "min_quality_score": 0.6,
        "min_usable_theme_ratio": 0.6,
        "backfill_require_warning_free": True,
    }
    values.update(overrides)
    return Settings(**values)
