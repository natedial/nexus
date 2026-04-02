import json
import tempfile
import unittest
from pathlib import Path

from src.dispatch_store import DispatchStore
from src.report_models import DispatchBatch


class DispatchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "dispatch.db"
        self.store = DispatchStore(self.db_path)

    def test_create_run_record_documents_and_finalize(self):
        run_id = self.store.create_run(
            run_type="email_dispatch",
            mode="debug",
            batch_key="legacy:2026-03-30:2026-03-31:US:rates:all",
            analysis_version=None,
            report_title="Research Dispatch",
            report_scope={"region": "US"},
            source_date_range={"start": "2026-03-30", "end": "2026-03-31"},
            document_count=2,
        )
        recorded = self.store.record_documents(
            run_id,
            [
                {
                    "id": 101,
                    "document_hash": "hash-101",
                    "source": "Goldman Sachs",
                    "source_date": "2026-03-30",
                    "document_name": "Rates Daily",
                },
                {
                    "id": 102,
                    "document_hash": "hash-102",
                    "source": "JPMorgan",
                    "source_date": "2026-03-31",
                    "document_name": "Macro Weekly",
                },
            ],
        )
        self.store.mark_pdf_generated(
            run_id,
            pdf_path="research_report_20260401_090000.pdf",
            throughline_count=4,
            callout_count=3,
        )
        self.store.mark_sent(run_id, ["a@example.com", "b@example.com"])
        snapshot_id = self.store.save_snapshot(
            run_id,
            snapshot_type="synthesis_snapshot",
            payload={"title": "Morning Run"},
        )
        self.store.finalize_run(run_id, status="completed")

        run = self.store.get_run(run_id)
        items = self.store.list_run_items(run_id)
        snapshots = self.store.list_snapshots(run_id)

        self.assertEqual(recorded, 2)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["throughline_count"], 4)
        self.assertEqual(run["callout_count"], 3)
        self.assertEqual(json.loads(run["recipients_json"]), ["a@example.com", "b@example.com"])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["research_id"], 101)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["id"], snapshot_id)

    def test_record_documents_accepts_dispatch_batch(self):
        batch = DispatchBatch.from_dict(
            {
                "batch_key": "2026-04-01:us:rates",
                "analysis_version": "2026-04-01",
                "documents": [
                    {
                        "research_id": 201,
                        "document_hash": "hash-201",
                        "document_name": "Desk Note",
                        "source": "Morgan Stanley",
                        "source_date": "2026-03-31",
                    }
                ],
            }
        )
        run_id = self.store.create_run(
            run_type="pdf_only",
            mode="debug",
            batch_key=batch.batch_key,
            analysis_version=batch.analysis_version,
            report_title="Research Dispatch",
            report_scope={},
            source_date_range={"start": "2026-03-31", "end": "2026-03-31"},
            document_count=1,
        )
        recorded = self.store.record_documents(run_id, batch)

        items = self.store.list_run_items(run_id)
        self.assertEqual(recorded, 1)
        self.assertEqual(items[0]["research_id"], 201)
        self.assertEqual(items[0]["document_hash"], "hash-201")


if __name__ == "__main__":
    unittest.main()
