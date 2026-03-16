import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.delta_engine import SynthesisDeltaTracker


def _result(title: str, through_lines: list[dict], callouts: list[dict] | None = None):
    return SimpleNamespace(
        title=title,
        document_count=12,
        through_lines=through_lines,
        callouts=callouts or [],
        analysis_paragraphs=[],
    )


class SynthesisDeltaTrackerTests(unittest.TestCase):
    def test_prepare_report_compares_against_matching_scope_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)

            previous_report = {
                "generated_at": "2026-03-08 09:00:00",
                "active_filters": {"region": "US"},
                "source_date_range": {"start": "2026-03-03", "end": "2026-03-08"},
            }
            previous_snapshot = tracker.create_snapshot(
                _result(
                    "Prior",
                    [
                        {
                            "lead": "Carry dominates while macro vol stays subdued",
                            "consensus_level": "strong_consensus",
                            "consensus_anchor": "Carry still pays in rangebound rates",
                            "supporting_themes": ["carry", "rangebound"],
                            "supporting_trades": ["Long belly carry"],
                            "supporting_sources": ["GS", "JPM"],
                            "key_insight": "Carry remains the default expression.",
                        },
                        {
                            "lead": "Curve steepeners are latent but not yet expressed",
                            "consensus_level": "moderate_consensus",
                            "consensus_anchor": "Steepening is a second-half story",
                            "supporting_themes": ["curve"],
                            "supporting_trades": ["2s10s steepeners"],
                            "supporting_sources": ["MS"],
                            "key_insight": "Steepeners are on deck, not in hand.",
                        },
                    ],
                ),
                previous_report,
            )
            tracker.save_snapshot(previous_snapshot)

            current_report = {
                "generated_at": "2026-03-15 09:00:00",
                "active_filters": {"region": "US"},
                "source_date_range": {"start": "2026-03-10", "end": "2026-03-15"},
            }
            current_snapshot, delta = tracker.prepare_report(
                _result(
                    "Current",
                    [
                        {
                            "lead": "Carry dominates while macro vol stays subdued",
                            "consensus_level": "strong_consensus",
                            "consensus_anchor": "Carry still pays in rangebound rates",
                            "supporting_themes": ["carry", "rangebound"],
                            "supporting_trades": ["Long belly carry"],
                            "supporting_sources": ["GS", "JPM"],
                            "key_insight": "Carry remains the default expression.",
                        },
                        {
                            "lead": "Curve steepeners are latent but not yet expressed",
                            "consensus_level": "mixed_views",
                            "consensus_anchor": "Steepening is now contested by front-end repricing",
                            "supporting_themes": ["curve", "repricing"],
                            "supporting_trades": ["2s10s steepeners", "payer hedges"],
                            "supporting_sources": ["MS", "Barclays"],
                            "key_insight": "Steepeners remain live if the front end stops re-tightening.",
                        },
                        {
                            "lead": "Funding stress is the hidden regime switch",
                            "consensus_level": "contrarian",
                            "consensus_anchor": "Funding only matters if liquidity deteriorates",
                            "supporting_themes": ["funding"],
                            "supporting_trades": ["SOFR basis widener"],
                            "supporting_sources": ["BofA"],
                            "key_insight": "Funding matters if reserve scarcity starts to bite.",
                        },
                    ],
                ),
                current_report,
            )

            self.assertEqual(current_snapshot["scope_key"], previous_snapshot["scope_key"])
            self.assertTrue(delta["baseline_available"])
            self.assertIn("1 new, 1 evolved, 1 persisted, 0 retired", delta["summary"])

            section_titles = [section["title"] for section in delta["sections"]]
            self.assertIn("What Changed", section_titles)
            self.assertIn("What Persisted", section_titles)
            self.assertIn("Trade Implications", section_titles)
            self.assertIn("Invalidation Watch", section_titles)

    def test_find_previous_snapshot_ignores_other_filter_scopes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)

            first_snapshot = tracker.create_snapshot(
                _result("EU", [{"lead": "ECB keeps duration rich"}]),
                {
                    "generated_at": "2026-03-01 09:00:00",
                    "active_filters": {"region": "EU"},
                    "source_date_range": {"start": "2026-02-24", "end": "2026-03-01"},
                },
            )
            tracker.save_snapshot(first_snapshot)

            current_snapshot = tracker.create_snapshot(
                _result("US", [{"lead": "Fed hold keeps carry alive"}]),
                {
                    "generated_at": "2026-03-08 09:00:00",
                    "active_filters": {"region": "US"},
                    "source_date_range": {"start": "2026-03-03", "end": "2026-03-08"},
                },
            )

            self.assertIsNone(tracker.find_previous_snapshot(current_snapshot))

    def test_find_previous_snapshot_ignores_reruns_of_same_source_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)

            first_snapshot = tracker.create_snapshot(
                _result("Earlier run", [{"lead": "Oil shock revives stagflation pricing"}]),
                {
                    "generated_at": "2026-03-15 17:23:28",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-11", "end": "2026-03-15"},
                },
            )
            tracker.save_snapshot(first_snapshot)

            rerun_snapshot = tracker.create_snapshot(
                _result("Rerun", [{"lead": "Oil shock revives stagflation pricing"}]),
                {
                    "generated_at": "2026-03-15 20:23:51",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-11", "end": "2026-03-15"},
                },
            )

            self.assertIsNone(tracker.find_previous_snapshot(rerun_snapshot))

    def test_find_previous_snapshot_ignores_same_day_prior_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)

            earlier_snapshot = tracker.create_snapshot(
                _result("Earlier same-day run", [{"lead": "Oil shock revives stagflation pricing"}]),
                {
                    "generated_at": "2026-03-15 09:00:00",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-08", "end": "2026-03-15"},
                },
            )
            tracker.save_snapshot(earlier_snapshot)

            current_snapshot = tracker.create_snapshot(
                _result("Later same-day run", [{"lead": "Fed/ECB policy split hardens"}]),
                {
                    "generated_at": "2026-03-15 21:07:01",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-11", "end": "2026-03-15"},
                },
            )

            self.assertIsNone(tracker.find_previous_snapshot(current_snapshot))

    def test_save_snapshot_writes_json_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)
            snapshot = tracker.create_snapshot(
                _result("Run", [{"lead": "Rates vol reprices policy tails"}]),
                {
                    "generated_at": "2026-03-15 12:00:00",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-10", "end": "2026-03-15"},
                },
            )

            tracker.save_snapshot(snapshot)

            self.assertTrue(history_file.exists())
            payload = json.loads(history_file.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["title"], "Run")

    def test_prepare_report_without_prior_snapshot_suppresses_delta_section(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            tracker = SynthesisDeltaTracker(history_file=history_file)

            current_snapshot, delta = tracker.prepare_report(
                _result(
                    "Baseline",
                    [
                        {
                            "lead": "Oil shock revives stagflation pricing",
                            "supporting_trades": ["Long front-end inflation protection"],
                        }
                    ],
                ),
                {
                    "generated_at": "2026-03-15 17:23:28",
                    "active_filters": {},
                    "source_date_range": {"start": "2026-03-11", "end": "2026-03-15"},
                },
            )

            self.assertEqual(current_snapshot["title"], "Baseline")
            self.assertFalse(delta["baseline_available"])
            self.assertEqual(delta["summary"], "")
            self.assertEqual(delta["sections"], [])


if __name__ == "__main__":
    unittest.main()
