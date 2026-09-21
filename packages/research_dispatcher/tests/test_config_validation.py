import unittest
from contextlib import ExitStack
from pathlib import Path
import tempfile
from unittest.mock import patch

from config import Config, parse_dispatch_input_mode


class ConfigValidationTests(unittest.TestCase):
    def _base_patches(self):
        return [
            patch.object(
                Config,
                "DATABASE_URL",
                "postgresql://nexus:nexus@localhost:5432/nexus",
            ),
            patch.object(Config, "SMTP_USERNAME", "mailer"),
            patch.object(Config, "SMTP_PASSWORD", "password"),
            patch.object(Config, "EMAIL_FROM", "from@example.com"),
            patch.object(Config, "EMAIL_TO", "to@example.com"),
        ]

    def test_parse_dispatch_input_mode_defaults_to_analyst(self):
        self.assertEqual(parse_dispatch_input_mode(None), "analyst")

    def test_parse_dispatch_input_mode_rejects_parser(self):
        with self.assertRaisesRegex(ValueError, "parser is no longer supported"):
            parse_dispatch_input_mode("parser")

    def test_parse_dispatch_input_mode_rejects_invalid_mode(self):
        with self.assertRaisesRegex(ValueError, "RESEARCH_DISPATCHER_INPUT_MODE"):
            parse_dispatch_input_mode("legacy")

    def test_validate_requires_analyst_batch_path(self):
        patchers = self._base_patches() + [
            patch.object(Config, "DISPATCH_INPUT_MODE", "analyst"),
            patch.object(Config, "ANALYST_BATCH_PATH", ""),
        ]
        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            with self.assertRaisesRegex(ValueError, "ANALYST_BATCH_PATH"):
                Config.validate()

    def test_validate_accepts_readable_analyst_batch_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_path = Path(tmpdir) / "batch.json"
            batch_path.write_text("{}")
            patchers = self._base_patches() + [
                patch.object(Config, "DISPATCH_INPUT_MODE", "analyst"),
                patch.object(Config, "ANALYST_BATCH_PATH", str(batch_path)),
            ]
            with ExitStack() as stack:
                for patcher in patchers:
                    stack.enter_context(patcher)
                Config.validate()


if __name__ == "__main__":
    unittest.main()
