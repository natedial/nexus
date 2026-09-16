"""Analyst settings read RESEARCH_ANALYST_* names, with legacy names as fallback."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from research_analysis_layer.config import Settings

_CLEARED = (
    "RESEARCH_ANALYST_PARSED_DB_URL",
    "PARSED_DB_URL",
    "RESEARCH_ANALYST_DEBATE_MODE",
    "ANALYST_DEBATE_MODE",
    "RESEARCH_ANALYST_BATCH_SIZE",
    "BATCH_SIZE",
)


def _settings(**env: str) -> Settings:
    base = {name: "" for name in _CLEARED}
    with patch.dict(os.environ, base, clear=False):
        for name in _CLEARED:
            del os.environ[name]
        with patch.dict(os.environ, env, clear=False):
            return Settings.from_env()


class EnvPrefixTest(unittest.TestCase):
    def test_prefixed_name_is_used(self) -> None:
        settings = _settings(RESEARCH_ANALYST_BATCH_SIZE="11")

        self.assertEqual(settings.batch_size, 11)

    def test_legacy_name_still_works(self) -> None:
        settings = _settings(BATCH_SIZE="7")

        self.assertEqual(settings.batch_size, 7)

    def test_prefixed_name_wins_over_legacy(self) -> None:
        settings = _settings(BATCH_SIZE="7", RESEARCH_ANALYST_BATCH_SIZE="11")

        self.assertEqual(settings.batch_size, 11)

    def test_redundant_package_word_is_dropped_from_prefixed_name(self) -> None:
        settings = _settings(RESEARCH_ANALYST_DEBATE_MODE="shadow")

        self.assertEqual(settings.analyst_debate_mode, "shadow")

    def test_legacy_analyst_prefix_still_works(self) -> None:
        settings = _settings(ANALYST_DEBATE_MODE="shadow")

        self.assertEqual(settings.analyst_debate_mode, "shadow")

    def test_shared_supabase_backs_the_parsed_store(self) -> None:
        settings = _settings(
            SUPABASE_URL="https://shared.supabase.co",
            SUPABASE_KEY="shared-key",
        )

        self.assertEqual(settings.parsed_db_url, "https://shared.supabase.co")
        self.assertEqual(settings.parsed_db_key, "shared-key")

    def test_package_override_beats_shared_supabase(self) -> None:
        settings = _settings(
            SUPABASE_URL="https://shared.supabase.co",
            SUPABASE_KEY="shared-key",
            RESEARCH_ANALYST_PARSED_DB_URL="https://analyst.supabase.co",
        )

        self.assertEqual(settings.parsed_db_url, "https://analyst.supabase.co")


if __name__ == "__main__":
    unittest.main()
