from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from research_analysis_layer.config import Settings

_NEXUS_ENV = {
    "NEXUS_DATABASE_URL": "postgresql://nexus:nexus@localhost:5432/nexus",
}


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
                **_NEXUS_ENV,
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
                **_NEXUS_ENV,
            }
            with patch.dict(os.environ, env, clear=False):
                previous = Path.cwd()
                os.chdir(analyst_root)
                try:
                    settings = Settings.from_env()
                finally:
                    os.chdir(previous)

            self.assertEqual(settings.state_db_path.resolve(), parser_state_path.resolve())

    def test_calendar_db_defaults_to_parsed_database_url(self) -> None:
        env = {
            "STATE_DB_PATH": "data/state.db",
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        self.assertEqual(
            settings.calendar_database_url,
            "postgresql://nexus:nexus@localhost:5432/nexus",
        )
        self.assertEqual(settings.calendar_match_source, "economic_events")

    def test_referent_granularity_defaults_coarse(self) -> None:
        env = {
            **_NEXUS_ENV,
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
            **_NEXUS_ENV,
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
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertEqual(settings.consensus_min_publishers, 2)
        self.assertFalse(
            any("consensus_min_publishers" in error for error in settings.validate())
        )

    def test_invalid_consensus_min_publishers_is_a_config_error(self) -> None:
        env = {
            **_NEXUS_ENV,
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
            **_NEXUS_ENV,
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
            **_NEXUS_ENV,
            "CONSENSUS_SHIFT_DIVERSITY_THRESHOLD": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid consensus_shift_diversity_threshold: must be >= 2, received 1",
            settings.validate(),
        )

    def test_digest_consensus_mode_defaults_to_off(self) -> None:
        env = {
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("RESEARCH_ANALYST_DIGEST_CONSENSUS_MODE", None)
            os.environ.pop("DIGEST_CONSENSUS_MODE", None)
            settings = Settings.from_env()
        self.assertEqual(settings.digest_consensus_mode, "off")
        self.assertFalse(
            any("digest_consensus_mode" in error for error in settings.validate())
        )

    def test_invalid_digest_consensus_mode_is_a_config_error(self) -> None:
        env = {
            **_NEXUS_ENV,
            "DIGEST_CONSENSUS_MODE": "maybe",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid digest_consensus_mode: expected off, shadow, or on, received 'maybe'",
            settings.validate(),
        )

    def test_promotion_gate_defaults_to_advisory(self) -> None:
        env = {
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("RESEARCH_ANALYST_PROMOTION_GATE_MODE", None)
            os.environ.pop("PROMOTION_GATE_MODE", None)
            settings = Settings.from_env()
        self.assertEqual(settings.promotion_gate_mode, "advisory")
        self.assertEqual(settings.promotion_gate_floors["divergence_grounded_rate"], 0.0)
        self.assertFalse(
            any("promotion_gate" in error for error in settings.validate())
        )

    def test_invalid_promotion_gate_mode_is_a_config_error(self) -> None:
        env = {
            **_NEXUS_ENV,
            "PROMOTION_GATE_MODE": "strict",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertIn(
            "invalid promotion_gate_mode: expected advisory or blocking, received 'strict'",
            settings.validate(),
        )

    def test_promotion_gate_floor_out_of_range_is_a_config_error(self) -> None:
        env = {
            **_NEXUS_ENV,
            "PROMOTION_GATE_FLOOR_DIVERGENCE_GROUNDED": "1.5",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()
        self.assertTrue(
            any(
                "promotion_gate_floor_divergence_grounded" in error
                for error in settings.validate()
            )
        )

    def test_nexus_database_url_promotes_analysis_store_to_postgres(self) -> None:
        env = {
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("RESEARCH_ANALYST_ANALYSIS_DB_URL", None)
            os.environ.pop("ANALYSIS_DB_URL", None)
            settings = Settings.from_env()

        self.assertTrue(settings.uses_postgres)
        self.assertEqual(
            settings.analysis_db_url,
            "postgresql://nexus:nexus@localhost:5432/nexus",
        )
        with self.assertRaises(ValueError):
            _ = settings.analysis_db_path

    def test_pipeline_ops_spool_path_uses_data_dir_for_postgres(self) -> None:
        env = {
            **_NEXUS_ENV,
        }
        with patch.dict(os.environ, env, clear=False):
            settings = Settings.from_env()

        self.assertEqual(
            settings.pipeline_ops_spool_path(),
            Path("data") / "pipeline_ops_spool.db",
        )

    def test_pipeline_ops_spool_path_uses_analysis_db_parent_for_sqlite(self) -> None:
        env = {
            "ANALYSIS_DB_URL": "sqlite:///tmp/custom/analysis.db",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("NEXUS_DATABASE_URL", None)
            os.environ.pop("RESEARCH_ANALYST_DATABASE_URL", None)
            settings = Settings.from_env()

        self.assertFalse(settings.uses_postgres)
        self.assertEqual(
            settings.pipeline_ops_spool_path(),
            Path("tmp/custom") / "pipeline_ops_spool.db",
        )


if __name__ == "__main__":
    unittest.main()
