import json
import tempfile
import unittest
from pathlib import Path

from src.main import _load_dispatch_documents


class _FakeDatabaseClient:
    def __init__(self):
        self.query_analysis_calls = 0

    def query_analysis(self):
        self.query_analysis_calls += 1
        return [{"id": 1, "document_name": "Parser Note", "parsed_data": {}}]


class DispatchInputModeTests(unittest.TestCase):
    def test_parser_mode_ignores_analyst_batch_path_and_queries_database(self):
        db = _FakeDatabaseClient()

        data, dispatch_batch, source_type = _load_dispatch_documents(
            input_mode="parser",
            analyst_batch_path="/path/that/should/not/be/read.json",
            db_client=db,
        )

        self.assertEqual(db.query_analysis_calls, 1)
        self.assertEqual(data[0]["document_name"], "Parser Note")
        self.assertIsNone(dispatch_batch)
        self.assertEqual(source_type, "parsed_research")

    def test_analyst_mode_loads_dispatch_batch(self):
        payload = {
            "batch_key": "batch-1",
            "analysis_version": "v1",
            "documents": [
                {
                    "research_id": 10,
                    "document_name": "Analyst Note",
                    "source": "Desk",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "batch.json"
            path.write_text(json.dumps(payload))

            data, dispatch_batch, source_type = _load_dispatch_documents(
                input_mode="analyst",
                analyst_batch_path=str(path),
                db_client=_FakeDatabaseClient(),
            )

        self.assertEqual(source_type, "analyst_batch")
        self.assertEqual(dispatch_batch.batch_key, "batch-1")
        self.assertEqual(data[0]["id"], 10)


if __name__ == "__main__":
    unittest.main()
