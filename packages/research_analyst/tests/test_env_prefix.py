"""Analyst settings read RESEARCH_ANALYST_* names, with legacy names as fallback."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from research_analysis_layer.config import Settings

_CLEARED = (
    "RESEARCH_ANALYST_PARSED_DATABASE_URL",
    "PARSED_DATABASE_URL",
    "RESEARCH_ANALYST_DEBATE_MODE",
    "ANALYST_DEBATE_MODE",
    "RESEARCH_ANALYST_BATCH_SIZE",
    "BATCH_SIZE",
    "RESEARCH_ANALYST_DIGEST_CONSENSUS_MODE",
    "DIGEST_CONSENSUS_MODE",
    "NEXUS_DATABASE_URL",
    "RESEARCH_ANALYST_DATABASE_URL",
)


def _settings(**env: str) -> Settings:
    base = {name: "" for name in _CLEARED}
    with patch.dict(os.environ, base, clear=False):
        for name in _CLEARED:
            os.environ.pop(name, None)
        with patch.dict(os.environ, env, clear=False):
            return Settings.from_env()


class EnvPrefixTest(unittest.TestCase):
    def test_prefixed_name_is_used(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            RESEARCH_ANALYST_BATCH_SIZE="11",
        )

        self.assertEqual(settings.batch_size, 11)

    def test_legacy_name_still_works(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            BATCH_SIZE="7",
        )

        self.assertEqual(settings.batch_size, 7)

    def test_prefixed_name_wins_over_legacy(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            BATCH_SIZE="7",
            RESEARCH_ANALYST_BATCH_SIZE="11",
        )

        self.assertEqual(settings.batch_size, 11)

    def test_redundant_package_word_is_dropped_from_prefixed_name(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            RESEARCH_ANALYST_DEBATE_MODE="shadow",
        )

        self.assertEqual(settings.analyst_debate_mode, "shadow")

    def test_legacy_analyst_prefix_still_works(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            ANALYST_DEBATE_MODE="shadow",
        )

        self.assertEqual(settings.analyst_debate_mode, "shadow")

    def test_digest_consensus_mode_prefixed_name(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            RESEARCH_ANALYST_DIGEST_CONSENSUS_MODE="shadow",
        )

        self.assertEqual(settings.digest_consensus_mode, "shadow")

    def test_digest_consensus_mode_legacy_name(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            DIGEST_CONSENSUS_MODE="on",
        )

        self.assertEqual(settings.digest_consensus_mode, "on")

    def test_shared_nexus_database_url_backs_the_parsed_store(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
        )

        self.assertEqual(
            settings.parsed_database_url,
            "postgresql://nexus:nexus@localhost:5432/nexus",
        )

    def test_package_override_beats_shared_nexus_url(self) -> None:
        settings = _settings(
            NEXUS_DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus",
            RESEARCH_ANALYST_PARSED_DATABASE_URL="postgresql://override/db",
        )

        self.assertEqual(settings.parsed_database_url, "postgresql://override/db")


if __name__ == "__main__":
    unittest.main()
