import unittest
from unittest.mock import patch

from config import Config


class ConfigValidationTests(unittest.TestCase):
    def _base_patches(self):
        return [
            patch.object(Config, "SUPABASE_URL", "https://example.supabase.co"),
            patch.object(Config, "SUPABASE_KEY", "service-key"),
            patch.object(Config, "SMTP_USERNAME", "mailer"),
            patch.object(Config, "SMTP_PASSWORD", "password"),
            patch.object(Config, "EMAIL_FROM", "from@example.com"),
            patch.object(Config, "EMAIL_TO", "to@example.com"),
        ]

    def test_validate_rejects_feedback_mode_without_signing_secret(self):
        patchers = self._base_patches() + [
            patch.object(Config, "FEEDBACK_ENABLED", True),
            patch.object(Config, "DOCUMENT_VIEWER_URL", "https://example.com/viewer"),
            patch.object(Config, "DOCUMENT_LINK_SECRET", ""),
        ]
        with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5], patchers[6], patchers[7], patchers[8]:
            with self.assertRaisesRegex(ValueError, "DOCUMENT_LINK_SECRET"):
                Config.validate()

    def test_validate_rejects_feedback_mode_with_http_viewer(self):
        patchers = self._base_patches() + [
            patch.object(Config, "FEEDBACK_ENABLED", True),
            patch.object(Config, "DOCUMENT_VIEWER_URL", "http://example.com/viewer"),
            patch.object(Config, "DOCUMENT_LINK_SECRET", "secret"),
        ]
        with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5], patchers[6], patchers[7], patchers[8]:
            with self.assertRaisesRegex(ValueError, "DOCUMENT_VIEWER_URL"):
                Config.validate()

    def test_validate_allows_secure_feedback_configuration(self):
        patchers = self._base_patches() + [
            patch.object(Config, "FEEDBACK_ENABLED", True),
            patch.object(Config, "DOCUMENT_VIEWER_URL", "https://example.com/viewer"),
            patch.object(Config, "DOCUMENT_LINK_SECRET", "secret"),
        ]
        with patchers[0], patchers[1], patchers[2], patchers[3], patchers[4], patchers[5], patchers[6], patchers[7], patchers[8]:
            Config.validate()


if __name__ == "__main__":
    unittest.main()
