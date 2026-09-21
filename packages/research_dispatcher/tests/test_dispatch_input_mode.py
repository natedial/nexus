import json
import tempfile
import unittest
from pathlib import Path

from src.dispatch_loader import load_dispatch_documents


class DispatchInputModeTests(unittest.TestCase):
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

            data, dispatch_batch, source_type = load_dispatch_documents(
                analyst_batch_path=str(path),
            )

        self.assertEqual(source_type, "analyst_batch")
        self.assertEqual(dispatch_batch.batch_key, "batch-1")
        self.assertEqual(data[0]["id"], 10)


if __name__ == "__main__":
    unittest.main()
