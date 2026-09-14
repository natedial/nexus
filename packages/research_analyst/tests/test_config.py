from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from research_analysis_layer.config import Settings


class ConfigTest(unittest.TestCase):
    def test_prefers_existing_relative_state_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            state_dir = tmp_path / "data"
            state_dir.mkdir()
            state_path = state_dir / "state.db"
            with sqlite3.connect(state_path) as conn:
                conn.execute(
                    "CREATE TABLE processed_files (file_id TEXT PRIMARY KEY)"
                )

            env = {
                "STATE_DB_PATH": "data/state.db",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                previous = Path.cwd()
                os.chdir(tmp_path)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(previous)

            self.assertEqual(settings.state_db_path.resolve(), state_path.resolve())

    def test_prefers_parser_sibling_when_local_file_is_not_state_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            analyst_root = root / "research_analyst"
            parser_root = root / "research_parser"
            analyst_root.mkdir()
            parser_root.mkdir()

            wrong_data_dir = analyst_root / "data"
            wrong_data_dir.mkdir()
            wrong_state_path = wrong_data_dir / "state.db"
            wrong_state_path.write_text("", encoding="utf-8")

            parser_data_dir = parser_root / "data"
            parser_data_dir.mkdir()
            parser_state_path = parser_data_dir / "state.db"
            with sqlite3.connect(parser_state_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE processed_files (
                        file_id TEXT PRIMARY KEY,
                        status TEXT
                    )
                    """
                )

            env = {
                "STATE_DB_PATH": "data/state.db",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "secret",
            }
            with patch.dict(os.environ, env, clear=False):
                previous = Path.cwd()
                os.chdir(analyst_root)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(previous)

            self.assertEqual(settings.state_db_path.resolve(), parser_state_path.resolve())

    def test_calendar_db_defaults_to_parsed_db_settings(self) -> None:
        env = {
            "STATE_DB_PATH": "data/state.db",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        self.assertEqual(settings.calendar_db_url, "https://example.supabase.co")
        self.assertEqual(settings.calendar_db_key, "secret")
        self.assertEqual(settings.calendar_match_source, "economic_events")

    def test_referent_granularity_defaults_coarse(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
            "REFERENT_GRANULARITY": "coarse",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertEqual(settings.referent_granularity, "coarse")
        self.assertFalse(
            any("referent_granularity" in error for error in settings.validate())
        )

    def test_invalid_referent_granularity_is_a_config_error(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
            "REFERENT_GRANULARITY": "medium",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid referent_granularity: expected coarse or fine, received 'medium'",
            settings.validate(),
        )

    def test_consensus_min_publishers_defaults_to_two(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertEqual(settings.consensus_min_publishers, 2)
        self.assertFalse(
            any("consensus_min_publishers" in error for error in settings.validate())
        )

    def test_invalid_consensus_min_publishers_is_a_config_error(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
            "CONSENSUS_MIN_PUBLISHERS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid consensus_min_publishers: must be >= 2, received 1",
            settings.validate(),
        )

    def test_consensus_shift_diversity_threshold_defaults_to_three(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertEqual(settings.consensus_shift_diversity_threshold, 3)
        self.assertFalse(
            any(
                "consensus_shift_diversity_threshold" in error
                for error in settings.validate()
            )
        )

    def test_invalid_consensus_shift_diversity_threshold_is_a_config_error(self) -> None:
        env = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_KEY": "secret",
            "CONSENSUS_SHIFT_DIVERSITY_THRESHOLD": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid consensus_shift_diversity_threshold: must be >= 2, received 1",
            settings.validate(),
        )


if __name__ == "__main__":
    unittest.main()
