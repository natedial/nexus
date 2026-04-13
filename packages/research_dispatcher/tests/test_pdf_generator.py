import tempfile
import unittest
from unittest.mock import patch

from reportlab.platypus import PageBreak, Paragraph

from config import Config
from src.pdf_generator import PDFGenerator


class PDFGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.generator = PDFGenerator(
            output_dir=self.tmpdir.name,
            format_rules_path="format_rules.yaml",
        )

    def test_normalize_pdf_text_value_replaces_unsupported_hyphens_recursively(self):
        data = {
            "lead": "Post‑SLR dealer capacity and near‑term inflation",
            "items": [
                "de‑escalation",
                {"text": "growth‑downside and front‑end pricing"},
            ],
        }

        normalized = self.generator._normalize_pdf_text_value(data)

        self.assertEqual(
            normalized["lead"],
            "Post-SLR dealer capacity and near-term inflation",
        )
        self.assertEqual(normalized["items"][0], "de-escalation")
        self.assertEqual(
            normalized["items"][1]["text"],
            "growth-downside and front-end pricing",
        )

    def test_section_headers_start_new_pages_by_default(self):
        elements = self.generator._create_section_header("Change Tracking")

        self.assertIsInstance(elements[0], PageBreak)
        self.assertIsInstance(elements[1], Paragraph)
        self.assertEqual(elements[1].getPlainText(), "Change Tracking")

    def test_executive_summary_section_does_not_force_page_break(self):
        elements = self.generator._create_executive_summary_section(
            {"analysis_paragraphs": [{"text": "Summary paragraph."}]}
        )

        self.assertIsInstance(elements[0], Paragraph)
        self.assertEqual(elements[0].getPlainText(), "Executive Summary")
        self.assertFalse(any(isinstance(element, PageBreak) for element in elements[:2]))

    def test_feedback_links_omitted_without_signing_secret(self):
        with patch.object(Config, "FEEDBACK_ENABLED", True), patch.object(
            Config, "DOCUMENT_VIEWER_URL", "https://example.com/viewer"
        ), patch.object(Config, "DOCUMENT_LINK_SECRET", ""):
            self.assertEqual(
                self.generator._create_feedback_links("doc-1", "item-1"),
                "",
            )

    def test_feedback_links_omitted_for_insecure_viewer_url(self):
        with patch.object(Config, "FEEDBACK_ENABLED", True), patch.object(
            Config, "DOCUMENT_VIEWER_URL", "http://example.com/viewer"
        ), patch.object(Config, "DOCUMENT_LINK_SECRET", "secret"):
            self.assertEqual(
                self.generator._create_feedback_links("doc-1", "item-1"),
                "",
            )

    def test_feedback_links_include_signed_full_text_url_for_secure_viewer(self):
        with patch.object(Config, "FEEDBACK_ENABLED", True), patch.object(
            Config, "DOCUMENT_VIEWER_URL", "https://example.com/viewer"
        ), patch.object(Config, "DOCUMENT_LINK_SECRET", "secret"), patch.object(
            Config, "FEEDBACK_BASE_URL", "https://feedback.example.com/submit"
        ):
            links = self.generator._create_feedback_links("doc-1", "item-1")

        self.assertIn("Full Text", links)
        self.assertIn("https://example.com/viewer?", links)
        self.assertIn("token=", links)


if __name__ == "__main__":
    unittest.main()
