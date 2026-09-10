from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
    DivergenceSide,
    GroundedReason,
)
from research_analysis_layer.services.consensus_shift import ConsensusShiftDetector


def _reason() -> GroundedReason:
    return GroundedReason(text="payrolls slowed", ref_key="span:1")


def _agreement(
    *,
    polarity: str,
    positions: list[str],
    diversity: int,
    horizon: str = "meeting_2026_09",
) -> ConsensusPoint:
    return ConsensusPoint(
        point="Fed hike path",
        positions=positions,
        reasons=[_reason()],
        confidence=0.8,
        subject="fed_policy",
        predicate="hike",
        polarity=polarity,
        horizon_bucket=horizon,
        source_diversity=diversity,
    )


def _split(*, positions: list[str], diversity: int) -> DivergencePoint:
    sides = [
        DivergenceSide(
            position=name,
            claim="hike call",
            polarity="up" if i == 0 else "down",
            reasons=[_reason()],
        )
        for i, name in enumerate(positions)
    ]
    return DivergencePoint(
        point="Fed hike path",
        sides=sides,
        subject="fed_policy",
        predicate="hike",
        horizon_bucket="meeting_2026_09",
        source_diversity=diversity,
    )


def _snapshot(
    *,
    agreements: list[ConsensusPoint] | None = None,
    disagreements: list[DivergencePoint] | None = None,
) -> ConsensusSnapshot:
    return ConsensusSnapshot(
        agreements=agreements or [],
        disagreements=disagreements or [],
        min_publishers=2,
    )


class ConsensusShiftDetectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = ConsensusShiftDetector(diversity_threshold=3)

    def test_first_snapshot_is_not_a_shift(self) -> None:
        snapshot = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        events = self.detector.detect({}, snapshot)
        self.assertEqual(events, [])

    def test_sign_flip_emits_one_event(self) -> None:
        first = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        previous = self.detector.states_from_snapshot(first)
        flipped = _snapshot(
            agreements=[
                _agreement(
                    polarity="up",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        events = self.detector.detect(previous, flipped)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, "source_consensus_shift")
        self.assertEqual(event.from_sign, "down")
        self.assertEqual(event.to_sign, "up")
        self.assertEqual(event.reasons, ["sign_flip"])
        self.assertEqual(event.from_source_diversity, 2)
        self.assertEqual(event.to_source_diversity, 2)

    def test_no_change_recompute_emits_none(self) -> None:
        snapshot = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        previous = self.detector.states_from_snapshot(snapshot)
        events = self.detector.detect(previous, snapshot)
        self.assertEqual(events, [])

    def test_diversity_crossing_threshold_emits_one_event(self) -> None:
        first = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        previous = self.detector.states_from_snapshot(first)
        grown = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs", "Morgan Stanley"],
                    diversity=3,
                )
            ]
        )
        events = self.detector.detect(previous, grown)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reasons, ["diversity_threshold"])
        self.assertEqual(events[0].from_source_diversity, 2)
        self.assertEqual(events[0].to_source_diversity, 3)

    def test_diversity_move_above_threshold_is_not_a_shift(self) -> None:
        first = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs", "Morgan Stanley"],
                    diversity=3,
                )
            ]
        )
        previous = self.detector.states_from_snapshot(first)
        grown = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Barclays", "Citi", "Goldman Sachs", "Morgan Stanley"],
                    diversity=4,
                )
            ]
        )
        self.assertEqual(self.detector.detect(previous, grown), [])

    def test_agreement_to_contested_is_a_sign_flip(self) -> None:
        first = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        previous = self.detector.states_from_snapshot(first)
        split = _snapshot(
            disagreements=[
                _split(
                    positions=["Barclays", "Citi", "Goldman Sachs"],
                    diversity=3,
                )
            ]
        )
        events = self.detector.detect(previous, split)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].from_sign, "down")
        self.assertEqual(events[0].to_sign, "contested")
        self.assertEqual(
            events[0].reasons, ["sign_flip", "diversity_threshold"]
        )

    def test_constructor_rejects_threshold_below_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "diversity_threshold must be >= 2"):
            ConsensusShiftDetector(diversity_threshold=1)


class ConsensusShiftStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.store = AnalysisStore(Path(self.tmp.name) / "analysis.db")
        self.detector = ConsensusShiftDetector(diversity_threshold=3)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _apply(self, snapshot: ConsensusSnapshot) -> tuple[int, int]:
        previous = self.store.list_consensus_cluster_state()
        events = self.detector.detect(previous, snapshot)
        inserted = self.store.insert_consensus_shift_events(events)
        self.store.replace_consensus_cluster_state(
            self.detector.states_from_snapshot(snapshot)
        )
        return len(events), inserted

    def test_sign_flip_persists_exactly_one_event(self) -> None:
        down = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        up = _snapshot(
            agreements=[
                _agreement(
                    polarity="up",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        detected, inserted = self._apply(down)
        self.assertEqual((detected, inserted), (0, 0))
        detected, inserted = self._apply(up)
        self.assertEqual((detected, inserted), (1, 1))
        detected, inserted = self._apply(up)
        self.assertEqual((detected, inserted), (0, 0))
        self.assertEqual(len(self.store.list_consensus_shift_events()), 1)

    def test_replaying_the_same_transition_is_idempotent(self) -> None:
        down = _snapshot(
            agreements=[
                _agreement(
                    polarity="down",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        up = _snapshot(
            agreements=[
                _agreement(
                    polarity="up",
                    positions=["Citi", "Goldman Sachs"],
                    diversity=2,
                )
            ]
        )
        self._apply(down)
        events = self.detector.detect(
            self.store.list_consensus_cluster_state(), up
        )
        self.assertEqual(self.store.insert_consensus_shift_events(events), 1)
        self.assertEqual(self.store.insert_consensus_shift_events(events), 0)
        self.assertEqual(len(self.store.list_consensus_shift_events()), 1)


class ConsensusShiftDoctorTest(unittest.TestCase):
    def test_doctor_report_counts_events_and_pending(self) -> None:
        from unittest.mock import MagicMock

        from research_analysis_layer.main import _consensus_shift_report

        store = MagicMock()
        store.list_consensus_cluster_state.return_value = {}
        store.list_consensus_shift_events.return_value = []
        store.list_argument_maps_for_consensus.return_value = []
        settings = MagicMock()
        settings.consensus_min_publishers = 2
        settings.consensus_shift_diversity_threshold = 3
        report = _consensus_shift_report(store, settings)
        self.assertEqual(report["event_count"], 0)
        self.assertEqual(report["cluster_state_count"], 0)
        self.assertEqual(report["pending_shift_count"], 0)


if __name__ == "__main__":
    unittest.main()
