import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.report_comparison import compare_reports


class ReportComparisonTests(unittest.TestCase):
    def test_compare_reports_emits_quality_review_metrics(self):
        parser_report = {
            "summary": {"total_documents": 1, "by_source": {"JPMorgan": 1}},
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-01"},
            "details": [{"id": 1, "source": "JPMorgan", "document_name": "Parser"}],
            "themes_analysis": [{"label": "Fed patience"}],
            "trades": [{"text": "Receive 2y rates"}],
            "through_lines": [{"lead": "Policy patience supports front-end carry."}],
            "callouts": [{"text": "The Fed can wait."}],
            "executive_summary": ["Parser summary paragraph."],
        }
        analyst_report = {
            "summary": {"total_documents": 2, "by_source": {"JPMorgan": 1, "GS": 1}},
            "source_date_range": {"start": "2026-04-01", "end": "2026-04-02"},
            "details": [
                {"id": 1, "source": "JPMorgan", "document_name": "Parser"},
                {"id": 2, "source": "GS", "document_name": "Analyst"},
            ],
            "themes_analysis": [
                {"label": "Fed patience"},
                {"label": "Term premium"},
            ],
            "trades": [{"text": "Pay 10y rates"}],
            "through_lines": [{"lead": "Supply risk lifts term premium."}],
            "callouts": [{"text": "Supply matters again."}],
            "talking_points": [{"text": "Discuss front-end repricing."}],
            "executive_summary": ["Analyst summary paragraph with more agent context."],
            "records": [
                {
                    "assertions": [{"summary_text": "Payrolls should slow."}],
                    "world_nodes": [{"node_key": "n1"}],
                }
            ],
        }

        comparison = compare_reports(parser_report, analyst_report)

        self.assertEqual(comparison["summary"]["document_count_delta"], 1)
        self.assertEqual(comparison["document_coverage"]["added_by_analyst"], ["2"])
        self.assertEqual(comparison["theme_labels"]["added_by_analyst"], ["Term premium"])
        self.assertEqual(comparison["trade_texts"]["missing_from_analyst"], ["Receive 2y rates"])
        self.assertEqual(
            comparison["analyst_only_fields"]["record_fields"]["analyst"]["assertions"],
            1,
        )
        self.assertTrue(comparison["representative_text_diffs"])

    def test_cli_writes_comparison_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            parser_path = tmp / "parser.json"
            analyst_path = tmp / "analyst.json"
            output_path = tmp / "comparison.json"
            parser_path.write_text(json.dumps({"summary": {"total_documents": 0}}))
            analyst_path.write_text(json.dumps({"summary": {"total_documents": 1}}))

            result = subprocess.run(
                [
                    sys.executable,
                    "compare_report_json.py",
                    "--parser-report-json",
                    str(parser_path),
                    "--analyst-report-json",
                    str(analyst_path),
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["summary"]["document_count_delta"], 1)


if __name__ == "__main__":
    unittest.main()
