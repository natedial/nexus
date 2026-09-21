from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models.dispatch_scope import DispatchScope


class AnalysisStoreDispatchTest(unittest.TestCase):
    def test_list_document_analysis_for_dispatch_latest_per_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AnalysisStore(Path(tmp) / "analysis.db")
            with store._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO document_analysis (
                        document_key, research_id, document_hash, analysis_version,
                        run_id, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-a",
                        1,
                        "hash-a",
                        "argmap-v1",
                        "run-1",
                        '{"payload_json": {"document": {"source": "GS"}}}',
                        "2026-03-01T00:00:00+00:00",
                        "2026-03-01T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO document_analysis (
                        document_key, research_id, document_hash, analysis_version,
                        run_id, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-a",
                        1,
                        "hash-a",
                        "argmap-v2",
                        "run-2",
                        '{"payload_json": {"document": {"source": "GS"}}}',
                        "2026-03-02T00:00:00+00:00",
                        "2026-03-02T00:00:00+00:00",
                    ),
                )

            scope = DispatchScope(
                batch_key="batch-1",
                analysis_version=None,
                date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
                document_keys=None,
                include_orphans=True,
            )
            rows = store.list_document_analysis_for_dispatch(scope)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["analysis_version"], "argmap-v2")

    def test_list_document_analysis_for_dispatch_filters_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AnalysisStore(Path(tmp) / "analysis.db")
            with store._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO document_analysis (
                        document_key, research_id, document_hash, analysis_version,
                        run_id, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-a",
                        1,
                        "hash-a",
                        "argmap-v1",
                        "run-1",
                        "{}",
                        datetime.now(timezone.utc).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO document_analysis (
                        document_key, research_id, document_hash, analysis_version,
                        run_id, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "doc-b",
                        2,
                        "hash-b",
                        "argmap-v2",
                        "run-2",
                        "{}",
                        datetime.now(timezone.utc).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

            scope = DispatchScope(
                batch_key="batch-2",
                analysis_version="argmap-v1",
                date_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
                document_keys=None,
                include_orphans=True,
            )
            rows = store.list_document_analysis_for_dispatch(scope)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["analysis_version"], "argmap-v1")


if __name__ == "__main__":
    unittest.main()
