"""Argument_map → morning attention dry path (canonical live feed)."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.claim_notes.library import FakeLibraryDigestReader
from src.claim_notes.ops import MorningAttentionOps
from src.claim_notes.project import project_argument_map_batch
from src.claim_notes.run_morning_attention import main as run_main
from src.claim_notes.watermark import RunWatermarkStore

ARG_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "claim_notes"
    / "argument_map_documents.json"
)


class ArgumentMapMorningAttentionTests(unittest.TestCase):
    def test_ops_argument_map_notes_no_project_library(self):
        docs = json.loads(ARG_FIXTURE.read_text(encoding="utf-8"))["documents"]
        notes = project_argument_map_batch(docs)
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            ops = MorningAttentionOps(
                library_reader=FakeLibraryDigestReader([]),
                watermark=RunWatermarkStore(Path(tmp) / "wm.json"),
                handoff_dir=handoff,
            )
            result = ops.run(
                notes=notes,
                calendar_events=[],
                now=datetime(2026, 10, 6, 10, 25, tzinfo=timezone.utc),
                dry_run=True,
                deliver=False,
                advance_watermark=False,
            )
            self.assertFalse(result.silent)
            self.assertTrue(all(p.source == "claim_note" for p in result.surface.points))
            self.assertNotIn("library", {p.source for p in result.surface.points})
            for point in result.surface.points:
                self.assertNotIn("LIBRARY desk", point.text)

    def test_cli_argument_map_json_dry_path(self):
        with TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            watermark = Path(tmp) / "wm.json"
            buf = StringIO()
            with redirect_stdout(buf):
                code = run_main(
                    [
                        "--argument-map-json",
                        str(ARG_FIXTURE),
                        "--handoff-dir",
                        str(handoff),
                        "--watermark",
                        str(watermark),
                        "--dry-run",
                        "--fake-delivery",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["claim_source"], "argument_map")
            self.assertFalse(payload["silent"])
            self.assertGreaterEqual(payload["claim_note_count"], 3)
            self.assertTrue(all(p["source"] == "claim_note" for p in payload["points"]))

    def test_cli_analyst_batch_dir_and_since(self):
        with TemporaryDirectory() as tmp:
            batch = Path(tmp) / "dispatch-batch-morning.json"
            batch.write_text(ARG_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
            (Path(tmp) / "latest.json").symlink_to(batch.name)
            handoff = Path(tmp) / "handoff"
            watermark = Path(tmp) / "wm.json"
            buf = StringIO()
            with redirect_stdout(buf):
                code = run_main(
                    [
                        "--analyst-batch-dir",
                        tmp,
                        "--since",
                        "2026-09-17",
                        "--handoff-dir",
                        str(handoff),
                        "--watermark",
                        str(watermark),
                        "--dry-run",
                        "--fake-delivery",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["silent"])
            # Only Powell 09-17 and 10-01 docs remain after since filter.
            self.assertLessEqual(payload["claim_note_count"], 2)

    def test_cli_empty_argument_map_silent(self):
        with TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty.json"
            empty.write_text('{"documents": []}\n', encoding="utf-8")
            handoff = Path(tmp) / "handoff"
            watermark = Path(tmp) / "wm.json"
            buf = StringIO()
            with redirect_stdout(buf):
                code = run_main(
                    [
                        "--argument-map-json",
                        str(empty),
                        "--handoff-dir",
                        str(handoff),
                        "--watermark",
                        str(watermark),
                        "--dry-run",
                        "--fake-delivery",
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload["silent"])


if __name__ == "__main__":
    unittest.main()
